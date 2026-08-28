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
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_("From Date cannot be after To Date."))
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Target Warehouse"), "fieldname": "target_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 185},
        {"label": _("Audited Transfers"), "fieldname": "audited_transfers", "fieldtype": "Int", "width": 105},
        {"label": _("Clean"), "fieldname": "clean_count", "fieldtype": "Int", "width": 65},
        {"label": _("Variance"), "fieldname": "variance_count", "fieldtype": "Int", "width": 70},
        {"label": _("Pending"), "fieldname": "pending_count", "fieldtype": "Int", "width": 70},
        {"label": _("Qty Sent"), "fieldname": "qty_sent", "fieldtype": "Float", "precision": 3, "width": 85},
        {"label": _("ABS Variance"), "fieldname": "abs_variance", "fieldtype": "Float", "precision": 3, "width": 95},
        {"label": _("Variance Value"), "fieldname": "variance_value", "fieldtype": "Currency", "width": 110},
        {"label": _("Ignored Qty"), "fieldname": "ignored_qty", "fieldtype": "Float", "precision": 3, "width": 85},
        {"label": _("Ignored Value"), "fieldname": "ignored_value", "fieldtype": "Currency", "width": 105},
        {"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 85},
        {"label": _("Receivers"), "fieldname": "receiver_count", "fieldtype": "Int", "width": 75},
    ]


def get_data(filters):
    records = frappe.get_list(
        "Stock Transfer Audit Record",
        filters={"docstatus": ["in", [1, 2]]},
        fields=[
            "name",
            "receive_stock",
            "target_warehouse",
            "audit_result",
            "processing_status",
            "total_sent_qty",
            "total_abs_variance_qty",
        ],
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
    selected = [
        r for r in records
        if r.receive_stock
        and dates.get(r.receive_stock)
        and getdate(filters.from_date) <= dates[r.receive_stock] <= getdate(filters.to_date)
        and (not filters.target_warehouse or r.target_warehouse == filters.target_warehouse)
    ]
    if not selected:
        return []

    names = [r.name for r in selected]
    values, ignored_values = get_variance_value_maps(names)
    _, usernames = get_receive_owner_maps([r.receive_stock for r in selected])

    ignored_qty = defaultdict(float)
    for row in frappe.get_all(
        "Stock Transfer Audit Item",
        filters={
            "parent": ["in", names],
            "parenttype": "Stock Transfer Audit Record",
            "action": "Ignore",
        },
        fields=["parent", "discrepancy_qty"],
        limit_page_length=0,
    ):
        ignored_qty[row.parent] += abs(flt(row.discrepancy_qty))

    grouped = {}

    for row in selected:
        key = row.target_warehouse or _("Unknown")
        g = grouped.setdefault(
            key,
            {
                "target_warehouse": row.target_warehouse,
                "audited_transfers": 0,
                "clean_count": 0,
                "variance_count": 0,
                "pending_count": 0,
                "qty_sent": 0.0,
                "abs_variance": 0.0,
                "variance_value": 0.0,
                "ignored_qty": 0.0,
                "ignored_value": 0.0,
                "_receivers": set(),
            },
        )

        g["audited_transfers"] += 1
        g["clean_count"] += 1 if row.audit_result == "Clean" else 0
        g["variance_count"] += 1 if row.audit_result == "Variance" else 0
        g["pending_count"] += 1 if row.processing_status == "Pending" else 0
        g["qty_sent"] += flt(row.total_sent_qty)
        g["abs_variance"] += flt(row.total_abs_variance_qty)
        g["variance_value"] += flt(values.get(row.name))
        g["ignored_qty"] += flt(ignored_qty.get(row.name))
        g["ignored_value"] += flt(ignored_values.get(row.name))
        receiver = usernames.get(row.receive_stock)
        if receiver:
            g["_receivers"].add(receiver)

    result = []
    for g in grouped.values():
        g["variance_pct"] = (
            (g["abs_variance"] / g["qty_sent"]) * 100 if g["qty_sent"] else 0
        )
        g["receiver_count"] = len(g.pop("_receivers"))
        result.append(g)

    result.sort(
        key=lambda r: (
            -r["variance_pct"],
            -r["variance_value"],
            r["target_warehouse"] or "",
        )
    )
    return result
