from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    conditions = ["1=1"]
    params = []

    for field in ("forecast_run", "branch", "main_group"):
        if filters.get(field):
            conditions.append(f"r.`{field}` = %s")
            params.append(filters.get(field))
    if filters.get("from_date"):
        conditions.append("r.date >= %s")
        params.append(filters.from_date)
    if filters.get("to_date"):
        conditions.append("r.date <= %s")
        params.append(filters.to_date)

    data = frappe.db.sql(
        f"""
        select r.forecast_run, r.date, r.branch, r.main_group,
               r.forecast_sales, r.forecast_sales_low, r.forecast_sales_high,
               r.actual_sales, r.absolute_error, r.signed_error,
               r.absolute_pct_error, r.confidence_pct, r.analog_samples
        from `tabSales Forecast Result` r
        where {' and '.join(conditions)}
        order by r.date asc, r.branch asc, r.main_group asc
        """,
        params,
        as_dict=True,
    )

    columns = [
        {"label": _("Forecast Run"), "fieldname": "forecast_run", "fieldtype": "Link", "options": "Sales Forecast Run", "width": 170},
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
        {"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 180},
        {"label": _("Group"), "fieldname": "main_group", "fieldtype": "Data", "width": 100},
        {"label": _("Forecast Sales"), "fieldname": "forecast_sales", "fieldtype": "Currency", "width": 130},
        {"label": _("Low"), "fieldname": "forecast_sales_low", "fieldtype": "Currency", "width": 115},
        {"label": _("High"), "fieldname": "forecast_sales_high", "fieldtype": "Currency", "width": 115},
        {"label": _("Actual Sales"), "fieldname": "actual_sales", "fieldtype": "Currency", "width": 130},
        {"label": _("Abs Error"), "fieldname": "absolute_error", "fieldtype": "Currency", "width": 120},
        {"label": _("APE %"), "fieldname": "absolute_pct_error", "fieldtype": "Percent", "width": 90},
        {"label": _("Confidence %"), "fieldname": "confidence_pct", "fieldtype": "Percent", "width": 105},
        {"label": _("Analogs"), "fieldname": "analog_samples", "fieldtype": "Int", "width": 80},
    ]

    actual_rows = [r for r in data if r.actual_sales is not None]
    total_forecast = sum(flt(r.forecast_sales) for r in actual_rows)
    total_actual = sum(flt(r.actual_sales) for r in actual_rows)
    total_abs = sum(flt(r.absolute_error) for r in actual_rows)
    total_signed = sum(flt(r.signed_error) for r in actual_rows)
    wape = total_abs / abs(total_actual) * 100 if total_actual else 0
    bias = total_signed / abs(total_actual) * 100 if total_actual else 0
    accuracy = max(0, 100 - wape) if actual_rows else 0

    summary = [
        {"value": total_forecast, "indicator": "Blue", "label": _("Forecast"), "datatype": "Currency"},
        {"value": total_actual, "indicator": "Green", "label": _("Actual"), "datatype": "Currency"},
        {"value": accuracy, "indicator": "Green" if accuracy >= 85 else "Orange", "label": _("Accuracy"), "datatype": "Percent"},
        {"value": bias, "indicator": "Green" if abs(bias) <= 5 else "Red", "label": _("Bias"), "datatype": "Percent"},
    ]

    daily = defaultdict(lambda: {"forecast": 0.0, "actual": 0.0, "has_actual": False})
    for row in data:
        key = str(row.date)
        daily[key]["forecast"] += flt(row.forecast_sales)
        if row.actual_sales is not None:
            daily[key]["actual"] += flt(row.actual_sales)
            daily[key]["has_actual"] = True

    labels = sorted(daily)
    datasets = [{"name": _("Forecast"), "values": [daily[d]["forecast"] for d in labels]}]
    if any(daily[d]["has_actual"] for d in labels):
        datasets.append({"name": _("Actual"), "values": [daily[d]["actual"] for d in labels]})
    chart = {
        "data": {"labels": labels, "datasets": datasets},
        "type": "line",
        "height": 300,
        "lineOptions": {"hideDots": 1, "regionFill": 1},
        "axisOptions": {"xIsSeries": 1},
    } if labels else None

    return columns, data, None, chart, summary
