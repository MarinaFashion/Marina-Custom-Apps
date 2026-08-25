import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry

from marina_custom_apps.stock_transfer_control.constants import (
    TYPE_RECEIVE_STOCK,
    TYPE_SEND_STOCK,
)
from marina_custom_apps.stock_transfer_control.services.transfer_policy import (
    validate_receive_stock_route,
)
from marina_custom_apps.stock_transfer_control.services.warehouse_policy import (
    validate_transit_warehouse,
)


def _lock_send_stock(send_stock):
    """Lock the original Send Stock row for duplicate-safe Receive creation."""
    rows = frappe.db.sql(
        """
        select name
        from `tabStock Entry`
        where name = %s
        for update
        """,
        (send_stock,),
        as_dict=True,
    )
    if not rows:
        frappe.throw(_("Stock Entry {0} does not exist.").format(send_stock))


def _get_existing_receive(send_stock):
    rows = frappe.get_all(
        "Stock Entry",
        filters={
            "outgoing_stock_entry": send_stock,
            "stock_entry_type": TYPE_RECEIVE_STOCK,
            "docstatus": ["<", 2],
        },
        fields=["name", "docstatus"],
        order_by="creation asc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _validate_original_send(send):
    if send.docstatus != 1:
        frappe.throw(
            _("Send Stock {0} must be submitted before End Transit.").format(send.name)
        )

    if send.stock_entry_type != TYPE_SEND_STOCK:
        frappe.throw(
            _("Stock Entry {0} is not a Marina Send Stock entry.").format(send.name)
        )

    if not send.add_to_transit:
        frappe.throw(
            _("Send Stock {0} is not marked Add to Transit.").format(send.name)
        )

    if not send.to_warehouse:
        frappe.throw(
            _("Send Stock {0} has no Transit target warehouse.").format(send.name)
        )

    if flt(send.per_transferred) >= 100:
        frappe.throw(
            _("Send Stock {0} has already been fully received.").format(send.name)
        )


def _prepare_receive_document(send):
    # Use ERPNext's own stock-in mapper so quantities, serial/batch references,
    # outgoing_stock_entry and remaining transfer quantities remain compatible
    # with ERPNext's transit accounting.
    receive = make_stock_in_entry(send.name)

    source_transit = send.to_warehouse
    _transit, final_physical = validate_transit_warehouse(source_transit)

    # Authorization is based on the receiving/final physical warehouse.
    # Warehouse Manager / Sales Supervisor need this physical warehouse in
    # Warehouse Users Allowed; Stock Manager / Administrator are privileged.
    validate_receive_stock_route(
        source_transit,
        final_physical,
        user=frappe.session.user,
    )

    receive.stock_entry_type = TYPE_RECEIVE_STOCK
    receive.purpose = "Material Transfer"
    receive.outgoing_stock_entry = send.name
    receive.add_to_transit = 0
    receive.from_warehouse = source_transit
    receive.to_warehouse = final_physical

    receive.custom_receive_via_end_transit = 1
    receive.custom_intended_final_warehouse = final_physical
    receive.custom_receiving_method = None

    for row in receive.items or []:
        row.s_warehouse = source_transit
        row.t_warehouse = final_physical

        # ERPNext's stock-in mapper links the source Stock Entry Detail in
        # ste_detail. Preserve it in Marina's explicit audit field too.
        if row.get("ste_detail"):
            row.custom_original_send_stock_detail = row.ste_detail

        # Capture expected quantity now. Actual receiving/reconciliation is
        # deliberately handled in the next phase.
        row.custom_sent_qty = row.qty

    return receive, final_physical


@frappe.whitelist()
def create_or_open_receive_stock(send_stock):
    """Create exactly one controlled Draft Receive Stock for a submitted Send.

    If a draft already exists, return it instead of creating a duplicate.
    A submitted Receive means the transfer is already completed.
    """
    if not send_stock:
        frappe.throw(_("Send Stock is required."))

    _lock_send_stock(send_stock)

    send = frappe.get_doc("Stock Entry", send_stock)
    _validate_original_send(send)

    existing = _get_existing_receive(send_stock)
    if existing:
        if existing.docstatus == 1:
            frappe.throw(
                _(
                    "Send Stock {0} already has submitted Receive Stock {1}."
                ).format(send_stock, existing.name)
            )

        # Re-check authorization against the current Transit -> Physical
        # mapping before exposing an existing draft.
        _transit, final_physical = validate_transit_warehouse(send.to_warehouse)
        validate_receive_stock_route(
            send.to_warehouse,
            final_physical,
            user=frappe.session.user,
        )

        return {
            "name": existing.name,
            "created": False,
            "source_warehouse": send.to_warehouse,
            "target_warehouse": final_physical,
        }

    receive, final_physical = _prepare_receive_document(send)

    # Respect normal Stock Entry create permissions for the logged-in user.
    receive.insert()

    return {
        "name": receive.name,
        "created": True,
        "source_warehouse": send.to_warehouse,
        "target_warehouse": final_physical,
    }
