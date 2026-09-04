from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today


def _require_read(doctype):
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(
            _("You do not have permission to read {0}.").format(doctype),
            frappe.PermissionError,
        )


@frappe.whitelist()
def upcoming_planned_qty(filters=None):
    _require_read("Forecast Buying Plan")
    return _upcoming()["qty"]


@frappe.whitelist()
def upcoming_planned_styles(filters=None):
    _require_read("Forecast Buying Plan")
    return _upcoming()["styles"]


@frappe.whitelist()
def latest_forecast_accuracy(filters=None):
    _require_read("Sales Forecast Run")
    rows = frappe.get_all(
        "Sales Forecast Run",
        filters={"status": "Completed", "actual_result_count": [">", 0]},
        fields=["accuracy_pct", "actual_result_count", "result_count"],
        order_by="generated_on desc",
        limit=50,
    )
    for row in rows:
        if cint(row.result_count) > 0 and cint(row.actual_result_count) == cint(row.result_count):
            return flt(row.accuracy_pct)
    return 0


@frappe.whitelist()
def data_mart_records(filters=None):
    _require_read("Sales Forecast Daily")
    return frappe.db.count("Sales Forecast Daily")


def _upcoming():
    start = getdate(today())
    end = start + timedelta(days=90)
    row = frappe.db.sql(
        """
        select coalesce(sum(i.planned_total_qty), 0) qty,
               coalesce(sum(i.planned_styles), 0) styles
        from `tabForecast Buying Plan` p
        inner join `tabForecast Buying Plan Item` i on i.parent = p.name
        where p.docstatus = 1 and p.status = 'Approved'
          and i.display_date between %s and %s
        """,
        (str(start), str(end)),
        as_dict=True,
    )[0]
    return row
