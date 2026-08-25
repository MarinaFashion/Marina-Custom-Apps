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
    """Return one exact Material Request route for all MR-linked rows.

    All Material Requests are treated identically. A Stock Entry created from
    a Material Request must resolve to one Physical -> Transit route.
    """
    routes = set()

    for row in doc.items or []:
        mr_name = row.get("material_request")
        if not mr_name:
            continue

        source = row.get("s_warehouse")
        target = row.get("t_warehouse")

        mr_item_name = row.get("material_request_item")
        if mr_item_name:
            mr_item = frappe.db.get_value(
                "Material Request Item",
                mr_item_name,
                ["from_warehouse", "warehouse"],
                as_dict=True,
            )
            if mr_item:
                source = mr_item.from_warehouse or source
                target = mr_item.warehouse or target

        if not source or not target:
            mr = frappe.db.get_value(
                "Material Request",
                mr_name,
                ["set_from_warehouse", "set_warehouse"],
                as_dict=True,
            )
            if mr:
                source = source or mr.set_from_warehouse
                target = target or mr.set_warehouse

        if not source or not target:
            frappe.throw(
                _(
                    "Material Request {0} does not provide a complete source "
                    "and target warehouse route."
                ).format(mr_name)
            )

        routes.add((source, target))

    if not routes:
        return None

    if len(routes) != 1:
        frappe.throw(
            _(
                "A Stock Entry created from Material Request must contain one "
                "consistent source and target warehouse route."
            )
        )

    return next(iter(routes))


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


def _reconcile_receive_rows(doc, require_actual=False):
    """Close Transit with Sent Qty; record physical count separately."""
    total_actual = 0.0

    for index, row in enumerate(doc.items or [], start=1):
        original_detail = row.get("custom_original_send_stock_detail") or row.get("ste_detail")
        if not original_detail:
            frappe.throw(_("Row {0}: Original Send Stock Detail is required.").format(index))

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
        actual_qty = flt(row.get("custom_actual_received_qty"))
        if actual_qty < 0:
            frappe.throw(_("Row {0}: Actual Received Qty cannot be negative.").format(index))

        row.qty = sent_qty
        row.transfer_qty = sent_qty * (flt(row.conversion_factor) or 1)
        row.custom_sent_qty = sent_qty
        row.custom_discrepancy_qty = sent_qty - actual_qty
        row.custom_unexpected_item = 0
        row.custom_original_send_stock_detail = original_detail
        total_actual += actual_qty

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


def validate_stock_entry(doc, method=None):
    if not doc.items:
        return

    mr_origin = _has_mr_origin(doc)

    if mr_origin:
        _validate_material_request_origin(doc)

    if doc.stock_entry_type not in MANAGED_TYPES:
        # Do not interfere with manufacturing/repack/other ERPNext stock entries.
        return

    _validate_child_route(doc)

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
        _reconcile_receive_rows(doc)

    elif doc.stock_entry_type == TYPE_TRANSFER_BETWEEN:
        validate_transfer_between_route(
            doc.from_warehouse,
            doc.to_warehouse,
        )


def validate_before_submit(doc, method=None):
    validate_stock_entry(doc, method=method)

    if doc.stock_entry_type == TYPE_RECEIVE_STOCK:
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
