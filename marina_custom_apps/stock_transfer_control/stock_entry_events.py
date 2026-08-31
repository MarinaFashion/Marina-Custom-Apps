import frappe
from frappe import _
from frappe.utils import flt

from marina_custom_apps.stock_transfer_control.constants import (
    TYPE_RECEIVE_STOCK,
    TYPE_SEND_STOCK,
    TYPE_TRANSFER_BETWEEN,
)
from marina_custom_apps.stock_transfer_control.services.transfer_policy import (
    validate_receive_stock_route,
    validate_send_stock_route,
    validate_transfer_between_route,
)


MANAGED_TYPES = {
    TYPE_SEND_STOCK,
    TYPE_RECEIVE_STOCK,
    TYPE_TRANSFER_BETWEEN,
}

RECEIVING_METHOD_NORMAL = "Normal Receiving"
RECEIVING_METHOD_MANUAL = "Manual / Barcode Receiving"
RECEIVING_METHODS = {
    RECEIVING_METHOD_NORMAL,
    RECEIVING_METHOD_MANUAL,
}


def _has_mr_origin(doc):
    return any(row.get("material_request") for row in (doc.items or []))


def _get_mr_route(doc):
    """Return the authoritative route from the originating Material Request(s).

    Never use mutable Stock Entry source/target values to derive this route.
    """
    mr_names = sorted(
        {
            row.get("material_request")
            for row in (doc.items or [])
            if row.get("material_request")
        }
    )
    if not mr_names:
        return None

    routes = set()

    for mr_name in mr_names:
        mr = frappe.db.get_value(
            "Material Request",
            mr_name,
            ["name", "docstatus", "set_from_warehouse", "set_warehouse"],
            as_dict=True,
        )
        if not mr:
            frappe.throw(_("Material Request {0} does not exist.").format(mr_name))
        if mr.docstatus != 1:
            frappe.throw(_("Material Request {0} must be submitted.").format(mr_name))

        mr_rows = frappe.get_all(
            "Material Request Item",
            filters={"parent": mr_name},
            fields=["from_warehouse", "warehouse"],
            limit_page_length=0,
        ) or [frappe._dict()]

        for mr_row in mr_rows:
            source = mr_row.from_warehouse or mr.set_from_warehouse
            target = mr_row.warehouse or mr.set_warehouse

            if not source or not target:
                frappe.throw(
                    _(
                        "Material Request {0} does not provide a complete source "
                        "and target warehouse route."
                    ).format(mr_name)
                )
            routes.add((source, target))

    if len(routes) != 1:
        frappe.throw(
            _(
                "A Stock Entry created from Material Request must contain one "
                "consistent source and target warehouse route."
            )
        )

    return next(iter(routes))


def _is_route_only_blank_row(row):
    return (
        not row.get("item_code")
        and flt(row.get("qty")) == 0
        and not row.get("material_request")
        and not row.get("material_request_item")
        and not row.get("batch_no")
        and not row.get("serial_no")
        and not row.get("serial_and_batch_bundle")
    )


def _remove_route_only_blank_rows(doc):
    if doc.stock_entry_type not in {TYPE_SEND_STOCK, TYPE_TRANSFER_BETWEEN}:
        return

    kept = [row for row in (doc.items or []) if not _is_route_only_blank_row(row)]
    if len(kept) != len(doc.items or []):
        doc.set("items", kept)
        for index, row in enumerate(doc.items or [], start=1):
            row.idx = index


def _set_transfer_total_qty(doc):
    if doc.stock_entry_type in {TYPE_SEND_STOCK, TYPE_TRANSFER_BETWEEN}:
        doc.custom_total_qty = sum(
            flt(row.qty) for row in (doc.items or []) if row.get("item_code")
        )
    elif doc.stock_entry_type == TYPE_RECEIVE_STOCK:
        doc.custom_total_qty = 0


def before_validate_stock_entry(doc, method=None):
    # Preserve Stock Auto Allocation logistics metadata/authoritative MR route first.
    from marina_custom_apps.stock_auto_allocation.stock_entry_events import preserve_allocation_route
    preserve_allocation_route(doc, method=method)
    _remove_route_only_blank_rows(doc)
    _set_transfer_total_qty(doc)

def _validate_child_route(doc):
    if not doc.from_warehouse or not doc.to_warehouse:
        frappe.throw(_("Source Warehouse and Target Warehouse are required."))

    for index, row in enumerate(doc.items or [], start=1):
        if row.s_warehouse != doc.from_warehouse:
            frappe.throw(
                _(
                    "Row {0}: Source Warehouse must equal the Stock Entry "
                    "Source Warehouse {1}."
                ).format(index, doc.from_warehouse)
            )

        if row.t_warehouse != doc.to_warehouse:
            frappe.throw(
                _(
                    "Row {0}: Target Warehouse must equal the Stock Entry "
                    "Target Warehouse {1}."
                ).format(index, doc.to_warehouse)
            )


def _validate_material_request_origin(doc):
    route = _get_mr_route(doc)
    if not route:
        return False

    source, target = route

    # MR -> Stock Entry is always the controlled Send Stock path.
    doc.stock_entry_type = TYPE_SEND_STOCK

    if doc.from_warehouse != source or doc.to_warehouse != target:
        frappe.throw(
            _(
                "Material Request route is {0} → {1}. The generated Stock "
                "Entry header route must remain exactly the same."
            ).format(source, target)
        )

    validate_send_stock_route(source, target)
    return True


def _validate_receiving_method(doc):
    receiving_method = doc.get("custom_receiving_method")
    if receiving_method not in RECEIVING_METHODS:
        frappe.throw(
            _("Receiving Method is required and must be selected through End Transit.")
        )

    if not doc.is_new():
        saved_method = frappe.db.get_value(
            "Stock Entry",
            doc.name,
            "custom_receiving_method",
        )
        if saved_method and saved_method != receiving_method:
            frappe.throw(
                _("Receiving Method cannot be changed after Receive Stock is created.")
            )


def _validate_unexpected_received_items(doc):
    rows = doc.get("custom_unexpected_received_items") or []
    if not rows:
        return

    if doc.stock_entry_type != TYPE_RECEIVE_STOCK:
        frappe.throw(_("Unexpected Received Items are allowed only on Receive Stock."))

    expected_item_codes = {row.item_code for row in (doc.items or []) if row.item_code}

    seen = set()
    for index, row in enumerate(rows, start=1):
        if not row.item_code:
            frappe.throw(_("Unexpected Received Item row {0}: Item Code is required.").format(index))

        if row.item_code in expected_item_codes:
            frappe.throw(
                _(
                    "Unexpected Received Item row {0}: Item {1} exists on the original "
                    "Send Stock. Update Actual Received Qty in the Items table instead."
                ).format(index, row.item_code)
            )

        actual_qty = flt(row.actual_received_qty)
        if actual_qty <= 0:
            frappe.throw(
                _("Unexpected Received Item row {0}: Actual Received Qty must be greater than zero.").format(index)
            )

        key = (row.item_code, row.barcode or "")
        if key in seen:
            frappe.throw(
                _("Unexpected Received Item row {0}: duplicate barcode/item. Use one row with the total count.").format(index)
            )
        seen.add(key)

        row.actual_received_qty = actual_qty
        row.discrepancy_qty = -actual_qty
        row.source_warehouse = doc.from_warehouse
        row.target_warehouse = doc.to_warehouse


def _reconcile_receive_rows(doc, require_actual=False):
    """Close Transit using only original Send rows; unexpected items are audit-only."""
    total_actual = 0.0

    for index, row in enumerate(doc.items or [], start=1):
        actual_qty = flt(row.get("custom_actual_received_qty"))
        if actual_qty < 0:
            frappe.throw(_("Row {0}: Actual Received Qty cannot be negative.").format(index))

        original_detail = row.get("custom_original_send_stock_detail") or row.get("ste_detail")
        if row.get("custom_unexpected_item") or not original_detail:
            frappe.throw(
                _(
                    "Row {0}: Unexpected items must be recorded in the "
                    "Unexpected Received Items table, not Stock Entry Items."
                ).format(index)
            )

        original_row = frappe.db.get_value(
            "Stock Entry Detail",
            original_detail,
            ["parent", "item_code", "qty"],
            as_dict=True,
        )
        if not original_row:
            frappe.throw(_("Row {0}: Original Send Stock Detail {1} does not exist.").format(index, original_detail))
        if original_row.parent != doc.outgoing_stock_entry:
            frappe.throw(_("Row {0}: Original Send Stock Detail does not belong to {1}.").format(index, doc.outgoing_stock_entry))
        if original_row.item_code != row.item_code:
            frappe.throw(_("Row {0}: Item must remain {1} from the original Send Stock.").format(index, original_row.item_code))

        sent_qty = flt(original_row.qty)
        row.qty = sent_qty
        row.transfer_qty = sent_qty * (flt(row.conversion_factor) or 1)
        row.custom_discrepancy_qty = row.qty - actual_qty
        row.custom_unexpected_item = 0
        row.custom_original_send_stock_detail = original_detail
        total_actual += actual_qty

    unexpected_rows = doc.get("custom_unexpected_received_items") or []
    unexpected_actual = sum(flt(row.actual_received_qty) for row in unexpected_rows)
    total_actual += unexpected_actual

    total_sent = sum(flt(row.qty) for row in (doc.items or []))
    expected_received = sum(
        flt(row.get("custom_actual_received_qty")) for row in (doc.items or [])
    )
    total_received = expected_received + unexpected_actual
    total_variance = total_sent - total_received
    expected_abs_variance = sum(
        abs(flt(row.qty) - flt(row.get("custom_actual_received_qty")))
        for row in (doc.items or [])
    )
    unexpected_abs_variance = sum(abs(flt(row.actual_received_qty)) for row in unexpected_rows)
    total_abs_variance = expected_abs_variance + unexpected_abs_variance

    doc.custom_total_sent_qty = total_sent
    doc.custom_total_received_qty = total_received
    doc.custom_total_variance_qty = total_variance
    doc.custom_total_abs_variance_qty = total_abs_variance

    if require_actual and total_actual <= 0:
        frappe.throw(_("At least one piece must be physically received before submission."))

def _validate_receive_origin(doc):
    _validate_receiving_method(doc)

    if not doc.get("custom_receive_via_end_transit"):
        frappe.throw(
            _(
                "Receive Stock cannot be created manually. Use End Transit "
                "from the original submitted Send Stock."
            )
        )

    original_name = doc.get("outgoing_stock_entry")
    if not original_name:
        frappe.throw(_("Original Send Stock is required for Receive Stock."))

    original = frappe.db.get_value(
        "Stock Entry",
        original_name,
        [
            "name",
            "docstatus",
            "stock_entry_type",
            "to_warehouse",
            "custom_intended_final_warehouse",
        ],
        as_dict=True,
    )

    if not original:
        frappe.throw(_("Original Send Stock {0} does not exist.").format(original_name))

    if original.docstatus != 1 or original.stock_entry_type != TYPE_SEND_STOCK:
        frappe.throw(
            _(
                "Original Stock Entry {0} must be a submitted Send Stock."
            ).format(original_name)
        )

    if doc.from_warehouse != original.to_warehouse:
        frappe.throw(
            _(
                "Receive Stock source must remain the original Send Stock "
                "Transit warehouse {0}."
            ).format(original.to_warehouse)
        )

    validate_receive_stock_route(doc.from_warehouse, doc.to_warehouse)


def _duplicate_managed_row_key(row):
    return (
        row.get("item_code") or "",
        row.get("barcode") or "",
        row.get("uom") or "",
        row.get("s_warehouse") or "",
        row.get("t_warehouse") or "",
        row.get("batch_no") or "",
        row.get("serial_no") or "",
    )


def _validate_no_duplicate_managed_rows(doc):
    if doc.stock_entry_type not in {TYPE_SEND_STOCK, TYPE_TRANSFER_BETWEEN}:
        return

    seen = {}
    for index, row in enumerate(doc.items or [], start=1):
        key = _duplicate_managed_row_key(row)
        if key in seen:
            frappe.throw(
                _(
                    "Rows {0} and {1} are duplicate transfer rows for item {2}. "
                    "Use one row and increase Qty instead."
                ).format(seen[key], index, row.item_code)
            )
        seen[key] = index


def validate_stock_entry(doc, method=None):
    _set_transfer_total_qty(doc)

    if not doc.items:
        return

    mr_origin = _has_mr_origin(doc)

    if mr_origin:
        _validate_material_request_origin(doc)

    if doc.stock_entry_type not in MANAGED_TYPES:
        # Do not interfere with manufacturing/repack/other ERPNext stock entries.
        return

    _validate_child_route(doc)
    _validate_no_duplicate_managed_rows(doc)

    if doc.stock_entry_type == TYPE_SEND_STOCK:
        intended_final = validate_send_stock_route(
            doc.from_warehouse,
            doc.to_warehouse,
        )

        current_intended = doc.get("custom_intended_final_warehouse")
        if not current_intended:
            # System-controlled field: derive it server-side when the client,
            # API, or MR-generation path has not populated it yet.
            doc.custom_intended_final_warehouse = intended_final
        elif current_intended != intended_final:
            frappe.throw(
                _(
                    "Intended Final Warehouse must be {0}, derived from "
                    "Transit warehouse {1}."
                ).format(intended_final, doc.to_warehouse)
            )

    elif doc.stock_entry_type == TYPE_RECEIVE_STOCK:
        _validate_receive_origin(doc)
        _validate_unexpected_received_items(doc)
        _reconcile_receive_rows(doc)

    elif doc.stock_entry_type == TYPE_TRANSFER_BETWEEN:
        validate_transfer_between_route(
            doc.from_warehouse,
            doc.to_warehouse,
        )


def validate_before_submit(doc, method=None):
    validate_stock_entry(doc, method=method)

    if doc.stock_entry_type == TYPE_RECEIVE_STOCK:
        _validate_unexpected_received_items(doc)
        _reconcile_receive_rows(doc, require_actual=True)

def validate_before_cancel(doc, method=None):
    if doc.stock_entry_type != TYPE_SEND_STOCK:
        return

    submitted_receive = frappe.db.exists(
        "Stock Entry",
        {
            "outgoing_stock_entry": doc.name,
            "stock_entry_type": TYPE_RECEIVE_STOCK,
            "docstatus": 1,
        },
    )
    if submitted_receive:
        frappe.throw(
            _(
                "Send Stock {0} cannot be cancelled while submitted Receive "
                "Stock {1} exists. Cancel the Receive Stock first."
            ).format(doc.name, submitted_receive)
        )

    draft_receives = frappe.get_all(
        "Stock Entry",
        filters={
            "outgoing_stock_entry": doc.name,
            "stock_entry_type": TYPE_RECEIVE_STOCK,
            "docstatus": 0,
        },
        pluck="name",
    )
    for receive_name in draft_receives:
        frappe.delete_doc(
            "Stock Entry",
            receive_name,
            ignore_permissions=True,
            force=True,
        )
