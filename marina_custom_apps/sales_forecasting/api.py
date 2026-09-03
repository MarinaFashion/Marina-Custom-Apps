import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from marina_custom_apps.sales_forecasting.services.data_mart import build_data_mart
from marina_custom_apps.sales_forecasting.services.forecast_engine import preview, run_forecast
from marina_custom_apps.sales_forecasting.services.readiness import refresh_buying_plan


@frappe.whitelist()
def refresh_buying_plan_progress(plan_name):
    plan = frappe.get_doc("Forecast Buying Plan", plan_name)
    plan.check_permission("write")
    return refresh_buying_plan(plan.name)


@frappe.whitelist()
def create_buying_plan_revision(plan_name):
    source = frappe.get_doc("Forecast Buying Plan", plan_name)
    if not frappe.has_permission("Forecast Buying Plan", "create"):
        frappe.throw(_("Not permitted to create Buying Plans."), frappe.PermissionError)

    versions = frappe.get_all(
        "Forecast Buying Plan",
        filters={"company": source.company, "plan_year": source.plan_year, "season": source.season},
        pluck="version",
        limit_page_length=0,
    )
    new_version = max([int(v or 0) for v in versions] + [0]) + 1
    doc = frappe.new_doc("Forecast Buying Plan")
    doc.company = source.company
    doc.plan_year = source.plan_year
    doc.season = source.season
    doc.version = new_version
    doc.effective_from = nowdate()
    doc.status = "Draft"
    doc.currency = source.currency
    doc.revision_of = source.name
    doc.notes = source.notes
    for row in source.items:
        doc.append("items", {
            "collection": row.collection,
            "drop": row.drop,
            "display_date": row.display_date,
            "main_group": row.main_group,
            "planned_styles": row.planned_styles,
            "planned_total_qty": row.planned_total_qty,
            "planned_total_cost": row.planned_total_cost,
            "planned_selling_value": row.planned_selling_value,
        })
    doc.insert()
    return doc.name


@frappe.whitelist()
def queue_data_mart_build(start_date, end_date):
    roles = set(frappe.get_roles())
    if not roles.intersection({"System Manager", "Sales Manager"}):
        frappe.throw(_("Sales Manager or System Manager role required to build forecast data."), frappe.PermissionError)
    start = str(getdate(start_date))
    end = str(getdate(end_date))
    job = frappe.enqueue(
        "marina_custom_apps.sales_forecasting.services.data_mart.build_data_mart",
        queue="long",
        timeout=7200,
        job_name=f"sales-forecast-data-mart-{start}-{end}",
        start_date=start,
        end_date=end,
    )
    return {"queued": True, "job_id": getattr(job, "id", None)}


@frappe.whitelist()
def build_data_mart_now(start_date, end_date):
    """Admin/debug endpoint for short ranges. Long rebuilds should use queue_data_mart_build."""
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("System Manager role required."), frappe.PermissionError)
    return build_data_mart(start_date, end_date)


@frappe.whitelist()
def queue_forecast_run(run_name):
    run = frappe.get_doc("Sales Forecast Run", run_name)
    run.check_permission("write")
    run.save()
    frappe.db.set_value("Sales Forecast Run", run.name, {"status": "Queued", "error_message": ""})
    frappe.db.commit()
    job = frappe.enqueue(
        "marina_custom_apps.sales_forecasting.services.forecast_engine.run_forecast",
        queue="long",
        timeout=7200,
        job_name=f"sales-forecast-run-{run.name}",
        run_name=run.name,
    )
    return {"queued": True, "job_id": getattr(job, "id", None), "run": run.name}


@frappe.whitelist()
def get_run_preview(run_name):
    run = frappe.get_doc("Sales Forecast Run", run_name)
    run.check_permission("read")
    return preview(run.name)


@frappe.whitelist()
def get_dashboard_summary():
    cfg = frappe.get_single("Sales Forecast Settings")
    today = getdate(nowdate())
    horizon = str(getdate(add_days(today, 90)))
    plan = frappe.db.sql(
        """
        select coalesce(sum(i.planned_total_qty), 0) qty,
               coalesce(sum(i.planned_styles), 0) styles,
               coalesce(sum(i.planned_selling_value), 0) selling
        from `tabForecast Buying Plan` p
        inner join `tabForecast Buying Plan Item` i on i.parent = p.name
        where p.docstatus = 1 and p.status = 'Approved'
          and i.display_date between %s and %s
        """,
        (str(today), horizon),
        as_dict=True,
    )[0]
    latest = frappe.get_all(
        "Sales Forecast Run",
        filters={"status": "Completed"},
        fields=["name", "run_type", "forecast_sales", "accuracy_pct", "bias_pct", "generated_on"],
        order_by="generated_on desc",
        limit=1,
    )
    data_through = frappe.db.sql("select max(date) from `tabSales Forecast Daily`")[0][0]
    return {
        "planned_qty_90d": plan.qty,
        "planned_styles_90d": plan.styles,
        "planned_selling_value_90d": plan.selling,
        "data_through": data_through,
        "latest_run": latest[0] if latest else None,
        "model": cfg.model_name,
    }
