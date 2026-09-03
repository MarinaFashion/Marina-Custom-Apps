from datetime import timedelta

import frappe
from frappe.utils import flt, getdate, today


def upcoming_planned_qty():
    return _upcoming()["qty"]


def upcoming_planned_styles():
    return _upcoming()["styles"]


def latest_forecast_accuracy():
    rows = frappe.get_all(
        "Sales Forecast Run",
        filters={"status": "Completed", "actual_sales": [">", 0]},
        fields=["accuracy_pct"],
        order_by="generated_on desc",
        limit=1,
    )
    return flt(rows[0].accuracy_pct) if rows else 0


def data_mart_records():
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
