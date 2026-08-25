import frappe
from frappe import _

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


def _validate_receive_origin(doc):
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

    elif doc.stock_entry_type == TYPE_TRANSFER_BETWEEN:
        validate_transfer_between_route(
            doc.from_warehouse,
            doc.to_warehouse,
        )


def validate_before_submit(doc, method=None):
    # Repeat the full validation at submit time so API/import/background
    # operations cannot bypass the control.
    validate_stock_entry(doc, method=method)


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
