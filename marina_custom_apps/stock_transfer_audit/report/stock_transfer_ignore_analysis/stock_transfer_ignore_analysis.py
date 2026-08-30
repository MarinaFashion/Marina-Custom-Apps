from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from marina_custom_apps.stock_transfer_audit.control_service import (
    get_receive_owner_maps,
    get_variance_value_maps,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.from_date or not filters.to_date:
        frappe.throw(_("From Date and To Date are required."))
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Ignore Reason"), "fieldname": "ignore_reason", "fieldtype": "Data", "width": 170},
        {"label": _("Target Warehouse"), "fieldname": "target_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
        {"label": _("Receiver Username"), "fieldname": "receiver_username", "fieldtype": "Data", "width": 140},
        {"label": _("Lines Ignored"), "fieldname": "line_count", "fieldtype": "Int", "width": 90},
        {"label": _("Ignored Qty"), "fieldname": "ignored_qty", "fieldtype": "Float", "precision": 3, "width": 90},
        {"label": _("Ignored Value"), "fieldname": "ignored_value", "fieldtype": "Currency", "width": 105},
        {"label": _("Audit Records"), "fieldname": "audit_record_count", "fieldtype": "Int", "width": 95},
    ]


def get_data(filters):
    records = frappe.get_all(
        "Stock Transfer Audit Record",
        filters={"docstatus": 1},
        fields=["name", "receive_stock", "target_warehouse"],
        limit_page_length=0,
    )
    if not records:
        return []

    receive_names = [r.receive_stock for r in records if r.receive_stock]
    receive_rows = frappe.get_all(
        "Stock Entry",
        filters={"name": ["in", receive_names]},
        fields=["name", "posting_date"],
        limit_page_length=0,
    ) if receive_names else []
    dates = {r.name: getdate(r.posting_date) for r in receive_rows}
    _, usernames = get_receive_owner_maps(receive_names)

    selected = [
        r for r in records
        if r.receive_stock
        and dates.get(r.receive_stock)
        and getdate(filters.from_date) <= dates[r.receive_stock] <= getdate(filters.to_date)
        and (not filters.target_warehouse or r.target_warehouse == filters.target_warehouse)
    ]
    if not selected:
        return []

    record_map = {r.name: r for r in selected}
    names = list(record_map)
    _, ignored_values = get_variance_value_maps(names)

    items = frappe.get_all(
        "Stock Transfer Audit Item",
        filters={
            "parent": ["in", names],
            "parenttype": "Stock Transfer Audit Record",
            "action": "Ignore",
        },
        fields=["parent", "discrepancy_qty", "ignore_reason"],
        limit_page_length=0,
    )

    # Allocate record-level ignored value proportionally by absolute ignored quantity.
    total_ignored_qty = defaultdict(float)
    for row in items:
        total_ignored_qty[row.parent] += abs(flt(row.discrepancy_qty))

    grouped = {}
    for row in items:
        if filters.ignore_reason and row.ignore_reason != filters.ignore_reason:
            continue

        record = record_map[row.parent]
        receiver = usernames.get(record.receive_stock, "")
        qty = abs(flt(row.discrepancy_qty))
        total_qty = total_ignored_qty.get(row.parent) or 0
        value = (
            flt(ignored_values.get(row.parent)) * qty / total_qty
            if total_qty else 0
        )

        key = (row.ignore_reason or _("Unspecified"), record.target_warehouse or "", receiver)
        g = grouped.setdefault(
            key,
            {
                "ignore_reason": row.ignore_reason or _("Unspecified"),
                "target_warehouse": record.target_warehouse,
                "receiver_username": receiver,
                "line_count": 0,
                "ignored_qty": 0.0,
                "ignored_value": 0.0,
                "_records": set(),
            },
        )
        g["line_count"] += 1
        g["ignored_qty"] += qty
        g["ignored_value"] += value
        g["_records"].add(row.parent)

    result = []
    for g in grouped.values():
        g["audit_record_count"] = len(g.pop("_records"))
        result.append(g)

    result.sort(
        key=lambda r: (
            -r["ignored_value"],
            -r["ignored_qty"],
            r["ignore_reason"],
        )
    )
    return result
