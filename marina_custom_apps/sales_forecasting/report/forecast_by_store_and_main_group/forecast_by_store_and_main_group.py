import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from marina_custom_apps.sales_forecasting.services.common import main_groups, settings


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get("forecast_run"):
        frappe.throw(_("Forecast Run is required."))

    run = frappe.get_doc("Sales Forecast Run", filters.forecast_run)
    run.check_permission("read")
    groups = main_groups(settings())

    conditions = ["forecast_run = %s"]
    params = [filters.forecast_run]
    if filters.get("branch"):
        conditions.append("branch = %s")
        params.append(filters.branch)
    if filters.get("from_date"):
        conditions.append("date >= %s")
        params.append(filters.from_date)
    if filters.get("to_date"):
        conditions.append("date <= %s")
        params.append(filters.to_date)

    rows = frappe.db.sql(
        f"""
        select date, branch, main_group,
               sum(forecast_sales) as forecast_sales,
               sum(forecast_units) as forecast_units
        from `tabSales Forecast Result`
        where {' and '.join(conditions)}
        group by date, branch, main_group
        order by branch asc, date asc, main_group asc
        """,
        params,
        as_dict=True,
    )

    sales = defaultdict(float)
    units = defaultdict(float)
    branches = set()
    dates_by_branch = defaultdict(set)
    for row in rows:
        branches.add(row.branch)
        day = str(row.date)
        dates_by_branch[row.branch].add(day)
        sales[(row.branch, day, row.main_group)] += flt(row.forecast_sales)
        units[(row.branch, day, row.main_group)] += flt(row.forecast_units)

    show_units = cint(filters.get("show_units"))
    columns = [{"label": _("Store / Date"), "fieldname": "store_date", "fieldtype": "Data", "width": 220}]
    for group in groups:
        columns.append({"label": _(group), "fieldname": _fieldname(group), "fieldtype": "Currency", "width": 125})
    columns.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "width": 135})
    if show_units:
        for group in groups:
            columns.append({"label": _("{0} Units").format(group), "fieldname": f"{_fieldname(group)}_units", "fieldtype": "Float", "precision": 1, "width": 110})
        columns.append({"label": _("Total Units"), "fieldname": "total_units", "fieldtype": "Float", "precision": 1, "width": 110})

    data = []
    company = {"name": "COMPANY_TOTAL", "store_date": _("COMPANY TOTAL"), "indent": 0, "is_group": 0}
    for group in groups:
        field = _fieldname(group)
        company[field] = sum(value for (branch, day, row_group), value in sales.items() if row_group == group)
        if show_units:
            company[f"{field}_units"] = sum(value for (branch, day, row_group), value in units.items() if row_group == group)
    company["total"] = sum(flt(company.get(_fieldname(group))) for group in groups)
    if show_units:
        company["total_units"] = sum(flt(company.get(f"{_fieldname(group)}_units")) for group in groups)
    data.append(company)

    for branch in sorted(branches):
        parent_name = f"BRANCH::{branch}"
        store_row = {"name": parent_name, "store_date": branch, "indent": 0, "is_group": 1}
        for group in groups:
            field = _fieldname(group)
            store_row[field] = sum(sales.get((branch, day, group), 0) for day in dates_by_branch[branch])
            if show_units:
                store_row[f"{field}_units"] = sum(units.get((branch, day, group), 0) for day in dates_by_branch[branch])
        store_row["total"] = sum(flt(store_row.get(_fieldname(group))) for group in groups)
        if show_units:
            store_row["total_units"] = sum(flt(store_row.get(f"{_fieldname(group)}_units")) for group in groups)
        data.append(store_row)

        for day in sorted(dates_by_branch[branch]):
            daily_row = {
                "name": f"{parent_name}::{day}",
                "parent": parent_name,
                "store_date": day,
                "indent": 1,
                "is_group": 0,
            }
            for group in groups:
                field = _fieldname(group)
                daily_row[field] = sales.get((branch, day, group), 0)
                if show_units:
                    daily_row[f"{field}_units"] = units.get((branch, day, group), 0)
            daily_row["total"] = sum(flt(daily_row.get(_fieldname(group))) for group in groups)
            if show_units:
                daily_row["total_units"] = sum(flt(daily_row.get(f"{_fieldname(group)}_units")) for group in groups)
            data.append(daily_row)

    summary = [{"value": company["total"], "indicator": "Blue", "label": _("Forecast Total"), "datatype": "Currency"}]
    return columns, data, None, None, summary


def _fieldname(value):
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return f"group_{text}" if text else "group_other"