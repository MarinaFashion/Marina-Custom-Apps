import json
from pathlib import Path

import frappe


NUMBER_CARDS = [
    ("Forecast Planned Qty 90D", "marina_custom_apps.sales_forecasting.kpi_service.upcoming_planned_qty"),
    ("Forecast Planned Styles 90D", "marina_custom_apps.sales_forecasting.kpi_service.upcoming_planned_styles"),
    ("Forecast Latest Accuracy", "marina_custom_apps.sales_forecasting.kpi_service.latest_forecast_accuracy"),
    ("Forecast Data Mart Records", "marina_custom_apps.sales_forecasting.kpi_service.data_mart_records"),
]



def app_after_install():
    # Preserve all existing Marina Custom Apps installation behavior, then install Forecasting.
    from marina_custom_apps.install import after_install as base_after_install
    base_after_install()
    after_install()


def app_after_migrate():
    # Preserve all existing Marina Custom Apps migration behavior, then sync Forecasting.
    from marina_custom_apps.install import after_migrate as base_after_migrate
    base_after_migrate()
    after_migrate()

def after_install():
    _ensure_number_cards()
    _sync_workspace()
    _ensure_indexes()
    _detect_calendar_safely()


def after_migrate():
    _ensure_number_cards()
    _sync_workspace()
    _ensure_indexes()
    _detect_calendar_safely()


def _ensure_number_cards():
    if not frappe.db.exists("DocType", "Number Card"):
        return
    for name, method in NUMBER_CARDS:
        values = {
            "label": name,
            "type": "Custom",
            "method": method,
            "is_public": 1,
            "show_percentage_stats": 0,
        }
        if frappe.db.exists("Number Card", name):
            frappe.db.set_value("Number Card", name, values, update_modified=False)
        else:
            doc = frappe.get_doc({"doctype": "Number Card", "name": name, **values})
            doc.insert(ignore_permissions=True)


def _sync_workspace():
    if not frappe.db.exists("DocType", "Workspace"):
        return
    path = Path(__file__).resolve().parent / "workspace" / "sales_forecasting" / "sales_forecasting.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    name = data["name"]
    child_tables = ("links", "shortcuts", "number_cards", "charts", "custom_blocks", "quick_lists", "roles")

    if frappe.db.exists("Workspace", name):
        doc = frappe.get_doc("Workspace", name)
        for field in (
            "label", "title", "module", "icon", "public", "is_hidden", "hide_custom",
            "content", "parent_page", "sequence_id",
        ):
            if field in data:
                doc.set(field, data.get(field))
        for table in child_tables:
            doc.set(table, [])
            for row in data.get(table, []):
                doc.append(table, row)
        if doc.meta.has_field("standard"):
            doc.standard = 1
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc(data)
        if doc.meta.has_field("standard"):
            doc.standard = 1
        doc.insert(ignore_permissions=True)

    if frappe.get_meta("Workspace").has_field("standard"):
        frappe.db.set_value("Workspace", name, "standard", 1, update_modified=False)
    frappe.clear_cache(doctype="Workspace")


def _ensure_indexes():
    for doctype, fields, name in (
        ("Sales Forecast Daily", ["date", "branch", "main_group"], "sf_daily_date_branch_group"),
        ("Sales Forecast Daily", ["branch", "main_group", "date"], "sf_daily_branch_group_date"),
        ("Sales Forecast Result", ["forecast_run", "date"], "sf_result_run_date"),
        ("Forecast Buying Plan Item", ["display_date", "main_group"], "sf_plan_display_group"),
    ):
        if not frappe.db.exists("DocType", doctype):
            continue
        try:
            frappe.db.add_index(doctype, fields, index_name=name)
        except Exception:
            # Idempotent across MariaDB/Postgres and existing installations.
            pass


def _detect_calendar_safely():
    try:
        from marina_custom_apps.sales_forecasting.services.common import detect_calendar_doctype
        detect_calendar_doctype()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sales Forecast Calendar Auto-Detection")
