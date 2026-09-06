from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


LEVELS = {
    "Detail": ("date", "branch", "main_group"),
    "Daily": ("date",),
    "Branch": ("branch",),
    "Main Group": ("main_group",),
    "Branch x Main Group": ("branch", "main_group"),
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("forecast_run"):
        frappe.throw(_("Forecast Run is required."))

    run = frappe.get_doc("Sales Forecast Run", filters.forecast_run)
    run.check_permission("read")

    level = filters.get("level") or "Branch x Main Group"
    dimensions = LEVELS.get(level)
    if not dimensions:
        frappe.throw(_("Unknown analysis level."))

    conditions = ["r.forecast_run = %s"]
    params = [filters.forecast_run]
    if filters.get("branch"):
        conditions.append("r.branch = %s")
        params.append(filters.branch)
    if filters.get("main_group"):
        conditions.append("r.main_group = %s")
        params.append(filters.main_group)
    if filters.get("from_date"):
        conditions.append("r.date >= %s")
        params.append(filters.from_date)
    if filters.get("to_date"):
        conditions.append("r.date <= %s")
        params.append(filters.to_date)

    source = frappe.db.sql(
        f"""
        select r.date, r.branch, r.main_group,
               r.forecast_sales, r.actual_sales, r.has_actual_data
        from `tabSales Forecast Result` r
        where {' and '.join(conditions)}
        order by r.date asc, r.branch asc, r.main_group asc
        """,
        params,
        as_dict=True,
    )

    buckets = defaultdict(list)
    for row in source:
        key = tuple(row.get(field) for field in dimensions)
        buckets[key].append(row)

    data = []
    for key in sorted(buckets, key=lambda value: tuple(str(v or "") for v in value)):
        rows = buckets[key]
        mapped = dict(zip(dimensions, key))
        data.append({
            "date": mapped.get("date"),
            "branch": mapped.get("branch"),
            "main_group": mapped.get("main_group"),
            **_metrics(rows),
        })

    columns = [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
        {"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 180},
        {"label": _("Main Group"), "fieldname": "main_group", "fieldtype": "Data", "width": 110},
        {"label": _("Forecast Sales"), "fieldname": "forecast_sales", "fieldtype": "Currency", "width": 130},
        {"label": _("Actual Sales"), "fieldname": "actual_sales", "fieldtype": "Currency", "width": 130},
        {"label": _("Variance"), "fieldname": "variance", "fieldtype": "Currency", "width": 120},
        {"label": _("WAPE %"), "fieldname": "wape", "fieldtype": "Percent", "width": 90},
        {"label": _("Accuracy %"), "fieldname": "accuracy", "fieldtype": "Percent", "width": 95},
        {"label": _("Bias %"), "fieldname": "bias", "fieldtype": "Percent", "width": 90},
        {"label": _("Actual Rows"), "fieldname": "actual_rows", "fieldtype": "Int", "width": 90},
        {"label": _("Result Rows"), "fieldname": "result_rows", "fieldtype": "Int", "width": 90},
        {"label": _("Coverage %"), "fieldname": "coverage_pct", "fieldtype": "Percent", "width": 95},
    ]

    overall = _metrics(source)
    summary = [
        {"value": overall["forecast_sales"], "indicator": "Blue", "label": _("Forecast"), "datatype": "Currency"},
        {"value": overall["actual_sales"], "indicator": "Green", "label": _("Actual"), "datatype": "Currency"},
        {"value": overall["coverage_pct"], "indicator": "Green" if overall["coverage_pct"] == 100 else "Orange", "label": _("Actual Coverage"), "datatype": "Percent"},
    ]
    if overall["accuracy"] is not None:
        summary.extend([
            {"value": overall["accuracy"], "indicator": "Green" if overall["accuracy"] >= 85 else "Orange", "label": _("Accuracy"), "datatype": "Percent"},
            {"value": overall["bias"], "indicator": "Green" if abs(overall["bias"] or 0) <= 5 else "Red", "label": _("Bias"), "datatype": "Percent"},
        ])

    return columns, data, None, _daily_chart(source), summary


def _metrics(rows):
    result_rows = len(rows)
    actual_rows = sum(1 for row in rows if int(row.has_actual_data or 0))
    forecast_sales = sum(flt(row.forecast_sales) for row in rows)
    covered_forecast = sum(flt(row.forecast_sales) for row in rows if int(row.has_actual_data or 0))
    actual_sales = sum(flt(row.actual_sales) for row in rows if int(row.has_actual_data or 0))
    coverage = actual_rows / result_rows * 100 if result_rows else 0
    complete = result_rows > 0 and actual_rows == result_rows

    if not complete:
        return {
            "forecast_sales": forecast_sales,
            "actual_sales": actual_sales,
            "variance": None,
            "wape": None,
            "accuracy": None,
            "bias": None,
            "actual_rows": actual_rows,
            "result_rows": result_rows,
            "coverage_pct": coverage,
        }

    abs_error = sum(abs(flt(row.forecast_sales) - flt(row.actual_sales)) for row in rows)
    signed_error = covered_forecast - actual_sales
    wape = abs_error / abs(actual_sales) * 100 if actual_sales else (0 if abs_error == 0 else None)
    bias = signed_error / abs(actual_sales) * 100 if actual_sales else (0 if signed_error == 0 else None)
    accuracy = max(0, 100 - wape) if wape is not None else None

    return {
        "forecast_sales": forecast_sales,
        "actual_sales": actual_sales,
        "variance": signed_error,
        "wape": wape,
        "accuracy": accuracy,
        "bias": bias,
        "actual_rows": actual_rows,
        "result_rows": result_rows,
        "coverage_pct": coverage,
    }


def _daily_chart(rows):
    daily = defaultdict(list)
    for row in rows:
        daily[str(row.date)].append(row)
    labels = sorted(daily)
    if not labels:
        return None

    datasets = [{
        "name": _("Forecast"),
        "values": [sum(flt(row.forecast_sales) for row in daily[day]) for day in labels],
    }]
    if all(daily[day] and all(int(row.has_actual_data or 0) for row in daily[day]) for day in labels):
        datasets.append({
            "name": _("Actual"),
            "values": [sum(flt(row.actual_sales) for row in daily[day]) for day in labels],
        })

    return {
        "data": {"labels": labels, "datasets": datasets},
        "type": "line",
        "height": 300,
        "lineOptions": {"hideDots": 1, "regionFill": 1},
        "axisOptions": {"xIsSeries": 1},
    }