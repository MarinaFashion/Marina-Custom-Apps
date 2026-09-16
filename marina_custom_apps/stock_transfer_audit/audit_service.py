import frappe
from frappe import _
from frappe.utils import flt

from marina_custom_apps.stock_transfer_audit.audit_policy import (
    controlled_receive_issue,
    effective_audit_window,
)
from marina_custom_apps.stock_transfer_audit.doctype.stock_transfer_control_settings.stock_transfer_control_settings import (
    get_audit_process_start_date,
)

SEND_TYPE = "Send Stock"
RECEIVE_TYPE = "Receive Stock"


def _submitted_receive_for_send(send_name):
    rows = frappe.get_all(
        "Stock Entry",
        filters={"outgoing_stock_entry": send_name, "stock_entry_type": RECEIVE_TYPE, "docstatus": 1},
        fields=["name"],
        order_by="posting_date desc, creation desc",
        limit_page_length=1,
    )
    return rows[0].name if rows else None


def get_transfer_snapshot(send_name, receive_name=None):
    if not send_name:
        frappe.throw(_("Original Send Stock is required."))
    send = frappe.get_doc("Stock Entry", send_name)
    if send.docstatus != 1 or send.stock_entry_type != SEND_TYPE:
        frappe.throw(_("Stock Entry {0} must be a submitted Send Stock.").format(send_name))

    receive_name = receive_name or _submitted_receive_for_send(send_name)
    receive = None
    if receive_name:
        receive = frappe.get_doc("Stock Entry", receive_name)
        if receive.docstatus != 1 or receive.stock_entry_type != RECEIVE_TYPE:
            frappe.throw(_("Stock Entry {0} must be a submitted Receive Stock.").format(receive_name))
        if receive.outgoing_stock_entry != send.name:
            frappe.throw(_("Receive Stock {0} is not linked to Send Stock {1}.").format(receive.name, send.name))

    items=[]; total_sent=0.0; total_received=0.0; total_abs_variance=0.0
    if receive:
        for row in receive.items or []:
            sent=flt(row.qty); actual=flt(row.get("custom_actual_received_qty")); variance=sent-actual
            items.append({
                "item_code":row.item_code,
                "sent_qty":sent,
                "actual_received_qty":actual,
                "discrepancy_qty":variance,
                "unexpected_item":0,
                "send_stock_detail":row.get("custom_original_send_stock_detail") or row.get("ste_detail"),
                "receive_stock_detail":row.name,
            })
            total_sent += sent; total_received += actual; total_abs_variance += abs(variance)
        for row in receive.get("custom_unexpected_received_items") or []:
            actual=flt(row.get("actual_received_qty")); variance=-actual
            items.append({
                "item_code":row.get("item_code"),
                "sent_qty":0,
                "actual_received_qty":actual,
                "discrepancy_qty":variance,
                "unexpected_item":1,
                "send_stock_detail":None,
                "receive_stock_detail":row.name,
            })
            total_received += actual; total_abs_variance += abs(variance)
    else:
        for row in send.items or []:
            sent=flt(row.qty); total_sent += sent
            items.append({
                "item_code":row.item_code,
                "sent_qty":sent,
                "actual_received_qty":0,
                "discrepancy_qty":sent,
                "unexpected_item":0,
                "send_stock_detail":row.name,
                "receive_stock_detail":None,
            })

    total_variance=total_sent-total_received
    return {
        "original_send_stock":send.name,
        "receive_stock":receive.name if receive else None,
        "posting_date":receive.posting_date if receive else send.posting_date,
        "source_warehouse":send.from_warehouse,
        "transit_warehouse":send.to_warehouse,
        "target_warehouse":receive.to_warehouse if receive else send.get("custom_intended_final_warehouse"),
        "total_sent_qty":total_sent,
        "total_received_qty":total_received,
        "total_variance_qty":total_variance,
        "total_abs_variance_qty":total_abs_variance,
        "audit_result":"Clean" if total_abs_variance == 0 else "Variance",
        "items":items,
    }


def _receive_filters(from_date, to_date):
    return {
        "docstatus": 1,
        "stock_entry_type": RECEIVE_TYPE,
        "posting_date": ["between", [from_date, to_date]],
        "outgoing_stock_entry": ["is", "set"],
    }


def validate_audit_run_receive(receive_name):
    receive = frappe.db.get_value(
        "Stock Entry",
        receive_name,
        [
            "posting_date",
            "custom_receive_via_end_transit",
            "custom_receiving_method",
        ],
        as_dict=True,
    )
    if not receive:
        frappe.throw(_("Receive Stock {0} no longer exists.").format(receive_name))

    process_start = get_audit_process_start_date()
    if receive.posting_date < process_start:
        frappe.throw(
            _(
                "Receive Stock {0} is before the Audit Process Start Date {1}. "
                "Reload Transfers."
            ).format(receive_name, process_start)
        )

    issue = controlled_receive_issue(
        receive.custom_receive_via_end_transit,
        receive.custom_receiving_method,
    )
    if issue:
        frappe.throw(
            _("Receive Stock {0} is not audit eligible: {1}.").format(
                receive_name, issue
            )
        )


def get_unaudited_received_transfers(from_date, to_date, include_summary=False):
    if not from_date or not to_date:
        frappe.throw(_("From Date and To Date are required."))
    if from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date."))

    window = effective_audit_window(
        from_date, to_date, get_audit_process_start_date()
    )
    summary = {
        "audit_process_start_date": window["process_start"],
        "legacy_excluded_count": 0,
        "previously_audited_count": 0,
    }

    if window["legacy_from"]:
        summary["legacy_excluded_count"] = frappe.db.count(
            "Stock Entry",
            filters=_receive_filters(window["legacy_from"], window["legacy_to"]),
        )

    if not window["effective_from"]:
        return {"transfers": [], **summary} if include_summary else []

    receives=frappe.get_all(
        "Stock Entry",
        filters=_receive_filters(window["effective_from"], window["effective_to"]),
        fields=[
            "name",
            "outgoing_stock_entry",
            "posting_date",
            "posting_time",
            "creation",
            "custom_receive_via_end_transit",
            "custom_receiving_method",
        ],
        order_by="posting_date asc, posting_time asc, creation asc",
        limit_page_length=0,
    )
    if not receives:
        return {"transfers": [], **summary} if include_summary else []

    configuration_issues = []
    for receive in receives:
        issue = controlled_receive_issue(
            receive.custom_receive_via_end_transit,
            receive.custom_receiving_method,
        )
        if issue:
            configuration_issues.append(f"{receive.name} ({issue})")

    if configuration_issues:
        preview = ", ".join(configuration_issues[:10])
        more = len(configuration_issues) - 10
        if more > 0:
            preview += _(" and {0} more").format(more)
        frappe.throw(
            _(
                "Receive Stock entries on or after {0} are missing the controlled "
                "receiving setup: {1}. Correct these entries before running the audit."
            ).format(window["process_start"], preview)
        )

    send_names = list(
        {r.outgoing_stock_entry for r in receives if r.outgoing_stock_entry}
    )
    existing = (
        set(
            frappe.get_all(
                "Stock Transfer Audit Record",
                filters={"original_send_stock": ["in", send_names]},
                pluck="original_send_stock",
                limit_page_length=0,
            )
        )
        if send_names
        else set()
    )
    summary["previously_audited_count"] = len(existing)
    result = []
    seen = set()
    for receive in receives:
        send_name = receive.outgoing_stock_entry
        if not send_name or send_name in existing or send_name in seen:
            continue
        meta = frappe.db.get_value(
            "Stock Entry",
            send_name,
            ["docstatus", "stock_entry_type"],
            as_dict=True,
        )
        if not meta or meta.docstatus != 1 or meta.stock_entry_type != SEND_TYPE:
            continue
        result.append(get_transfer_snapshot(send_name, receive.name))
        seen.add(send_name)
    return {"transfers": result, **summary} if include_summary else result
