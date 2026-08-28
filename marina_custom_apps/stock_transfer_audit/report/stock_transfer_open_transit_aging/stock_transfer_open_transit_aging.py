import frappe
from frappe import _

from marina_custom_apps.stock_transfer_audit.control_service import (
    get_open_transit_rows,
    get_usernames,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Status"), "fieldname": "aging_status", "fieldtype": "Data", "width": 90},
        {"label": _("Route"), "fieldname": "transfer_route", "fieldtype": "Data", "width": 105},
        {"label": _("Age Days"), "fieldname": "age_days", "fieldtype": "Int", "width": 75},
        {"label": _("SLA Days"), "fieldname": "sla_days", "fieldtype": "Int", "width": 75},
        {"label": _("Send Stock"), "fieldname": "send_stock", "fieldtype": "Link", "options": "Stock Entry", "width": 145},
        {"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
        {"label": _("Source Warehouse"), "fieldname": "source_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
        {"label": _("Transit Warehouse"), "fieldname": "transit_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
        {"label": _("Target Warehouse"), "fieldname": "target_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
        {"label": _("Qty Sent"), "fieldname": "qty_sent", "fieldtype": "Float", "precision": 3, "width": 85},
        {"label": _("Stock Value"), "fieldname": "stock_value", "fieldtype": "Currency", "width": 105},
        {"label": _("Receive Draft"), "fieldname": "receive_draft", "fieldtype": "Link", "options": "Stock Entry", "width": 140},
        {"label": _("Created By"), "fieldname": "receiver_username", "fieldtype": "Data", "width": 130},
    ]


def get_data(filters):
    rows = get_open_transit_rows(filters.company)
    usernames = get_usernames([r.owner for r in rows])

    result = []
    for row in rows:
        if filters.status and row.aging_status != filters.status:
            continue
        if filters.source_warehouse and row.source_warehouse != filters.source_warehouse:
            continue
        if filters.target_warehouse and row.target_warehouse != filters.target_warehouse:
            continue

        row.receiver_username = usernames.get(row.owner, row.owner)
        result.append(row)

    priority = {"Critical": 0, "Overdue": 1, "Due Soon": 2, "Open": 3}
    result.sort(key=lambda r: (priority.get(r.aging_status, 9), -r.age_days, r.send_stock))
    return result
