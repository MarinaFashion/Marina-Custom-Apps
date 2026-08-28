from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, today

from marina_custom_apps.stock_transfer_audit.control_service import (
    get_receive_owner_maps,
    get_settings,
    get_variance_value_maps,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Priority"), "fieldname": "priority", "fieldtype": "Data", "width": 80},
        {"label": _("Age Days"), "fieldname": "age_days", "fieldtype": "Int", "width": 75},
        {"label": _("Audit Record"), "fieldname": "audit_record", "fieldtype": "Link", "options": "Stock Transfer Audit Record", "width": 145},
        {"label": _("Receiver"), "fieldname": "receiver_username", "fieldtype": "Data", "width": 130},
        {"label": _("Source Warehouse"), "fieldname": "source_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 165},
        {"label": _("Target Warehouse"), "fieldname": "target_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 165},
        {"label": _("ABS Variance"), "fieldname": "abs_variance", "fieldtype": "Float", "precision": 3, "width": 95},
        {"label": _("Variance Value"), "fieldname": "variance_value", "fieldtype": "Currency", "width": 110},
        {"label": _("Ignored Qty"), "fieldname": "ignored_qty", "fieldtype": "Float", "precision": 3, "width": 90},
        {"label": _("Ignored Value"), "fieldname": "ignored_value", "fieldtype": "Currency", "width": 105},
        {"label": _("Correction Required Qty"), "fieldname": "correction_required_qty", "fieldtype": "Float", "precision": 3, "width": 135},
        {"label": _("Draft Corrections"), "fieldname": "draft_corrections", "fieldtype": "Int", "width": 105},
    ]


def get_data(filters):
    record_filters = {"docstatus": 1, "processing_status": "Pending"}

    if filters.source_warehouse:
        record_filters["source_warehouse"] = filters.source_warehouse
    if filters.target_warehouse:
        record_filters["target_warehouse"] = filters.target_warehouse

    records = frappe.get_list(
        "Stock Transfer Audit Record",
        filters=record_filters,
        fields=[
            "name",
            "receive_stock",
            "source_warehouse",
            "target_warehouse",
            "total_abs_variance_qty",
            "creation",
        ],
        order_by="creation asc",
        limit_page_length=0,
    )
    if not records:
        return []

    names = [r.name for r in records]
    _, username_by_receive = get_receive_owner_maps([r.receive_stock for r in records])
    values, ignored_values = get_variance_value_maps(names)

    ignored_qty = defaultdict(float)
    correction_required = defaultdict(float)

    for row in frappe.get_all(
        "Stock Transfer Audit Item",
        filters={"parent": ["in", names], "parenttype": "Stock Transfer Audit Record"},
        fields=["parent", "discrepancy_qty", "action"],
        limit_page_length=0,
    ):
        variance = flt(row.discrepancy_qty)
        qty = abs(variance)

        if row.action == "Ignore":
            ignored_qty[row.parent] += qty
        elif (
            variance > 0 and row.action == "Move to Source"
        ) or (
            variance < 0 and row.action == "Move to Target"
        ):
            correction_required[row.parent] += qty

    draft_counts = defaultdict(int)
    for row in frappe.get_all(
        "Stock Entry",
        filters={
            "custom_stock_transfer_audit_record": ["in", names],
            "docstatus": 0,
        },
        fields=["custom_stock_transfer_audit_record"],
        limit_page_length=0,
    ):
        draft_counts[row.custom_stock_transfer_audit_record] += 1

    settings = get_settings()
    current = getdate(today())
    min_age = max(cint(filters.minimum_age_days), 0)
    result = []

    for row in records:
        age = max(date_diff(current, getdate(row.creation)), 0)
        if age < min_age:
            continue

        receiver = username_by_receive.get(row.receive_stock, "")
        if filters.receiver_username and receiver != filters.receiver_username:
            continue

        variance_value = flt(values.get(row.name))
        large = (
            flt(row.total_abs_variance_qty) >= flt(settings.large_variance_qty_threshold)
            or variance_value >= flt(settings.large_variance_value_threshold)
        )

        if age > cint(settings.pending_audit_sla_days):
            priority = "Critical" if large else "Overdue"
        else:
            priority = "High" if large else "Open"

        result.append(
            {
                "priority": priority,
                "age_days": age,
                "audit_record": row.name,
                "receiver_username": receiver,
                "source_warehouse": row.source_warehouse,
                "target_warehouse": row.target_warehouse,
                "abs_variance": row.total_abs_variance_qty,
                "variance_value": variance_value,
                "ignored_qty": ignored_qty.get(row.name, 0),
                "ignored_value": ignored_values.get(row.name, 0),
                "correction_required_qty": correction_required.get(row.name, 0),
                "draft_corrections": draft_counts.get(row.name, 0),
            }
        )

    priority_order = {"Critical": 0, "Overdue": 1, "High": 2, "Open": 3}
    result.sort(
        key=lambda r: (
            priority_order.get(r["priority"], 9),
            -r["age_days"],
            -flt(r["variance_value"]),
        )
    )
    return result
