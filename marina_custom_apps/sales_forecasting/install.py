import json
from pathlib import Path

import frappe
from frappe.utils import cint, flt


NUMBER_CARDS = [
    (
        "Forecast Planned Qty 90D",
        "marina_custom_apps.sales_forecasting.kpi_service.upcoming_planned_qty",
        "Forecast Buying Plan",
    ),
    (
        "Forecast Planned Styles 90D",
        "marina_custom_apps.sales_forecasting.kpi_service.upcoming_planned_styles",
        "Forecast Buying Plan",
    ),
    (
        "Forecast Latest Accuracy",
        "marina_custom_apps.sales_forecasting.kpi_service.latest_forecast_accuracy",
        "Sales Forecast Run",
    ),
    (
        "Forecast Data Mart Records",
        "marina_custom_apps.sales_forecasting.kpi_service.data_mart_records",
        "Sales Forecast Daily",
    ),
]

TEXT_SETTING_DEFAULTS = {
    "company": "Marina",
    "selling_price_list": "Standard Selling",
    "currency": "SAR",
    "main_groups": "Dresses,Uppers,Bottoms",
    "branch_company_field": "custom_company",
    "branch_opening_date_field": "custom_opening_date",
    "branch_store_space_field": "custom_store_space",
    "branch_cluster_field": "custom_cluster",
    "branch_warehouse_field": "custom_warehouse",
    "branch_pos_profile_field": "custom_pos_profile",
    "branch_city_field": "custom_city",
    "item_main_group_field": "custom_item_main_group",
    "item_sub_group_field": "item_sub_group",
    "item_year_field": "item_year",
    "item_season_field": "season",
    "item_collection_field": "collection",
    "item_drop_field": "custom_drop",
    "item_display_date_field": "display_date",
    "calendar_doctype": "Marina Calendar Date",
    "calendar_date_field": "date",
    "calendar_event_field": "event",
    "calendar_hijri_date_field": "hijri_date",
    "calendar_hijri_month_name_field": "hijri_m_name",
    "calendar_hijri_day_field": "day",
    "calendar_hijri_month_field": "month",
    "calendar_hijri_year_field": "year",
    "history_start_date": "2023-01-01",
    "model_name": "Marina Analog Ensemble v1",
}

POSITIVE_SETTING_DEFAULTS = {
    "daily_refresh_lookback_days": 14,
    "displayed_style_window_days": 180,
    "inventory_active_window_days": 365,
    "ignore_pos_shift_over_hours": 24,
    "data_mart_batch_size": 5000,
    "lookback_years": 3,
    "recency_half_life_days": 365,
    "minimum_analog_samples": 20,
    "confidence_z": 1.28,
}

DAY_SETTING_DEFAULTS = {
    "salary_pre_start_day": 25,
    "salary_peak_start_day": 27,
    "salary_peak_end_next_month_day": 3,
    "salary_decline_end_day": 9,
}


def app_after_install():
    from marina_custom_apps.install import after_install as base_after_install

    base_after_install()
    from marina_custom_apps.marina_calendar.install import after_install as calendar_after_install

    calendar_after_install()
    after_install()


def app_after_migrate():
    from marina_custom_apps.install import after_migrate as base_after_migrate

    base_after_migrate()
    from marina_custom_apps.marina_calendar.install import after_migrate as calendar_after_migrate

    calendar_after_migrate()
    after_migrate()


def after_install():
    _repair_settings_defaults()
    _ensure_number_cards()
    _sync_workspace()
    _ensure_indexes()
    _detect_calendar_safely()


def after_migrate():
    _repair_settings_defaults()
    _ensure_number_cards()
    _sync_workspace()
    _ensure_indexes()
    _detect_calendar_safely()


def _repair_settings_defaults():
    if not frappe.db.exists("DocType", "Sales Forecast Settings"):
        return

    cfg = frappe.get_single("Sales Forecast Settings")
    updates = {}

    for fieldname, default in TEXT_SETTING_DEFAULTS.items():
        value = cfg.get(fieldname)
        if value is None or (isinstance(value, str) and not value.strip()):
            updates[fieldname] = default

    for fieldname, default in POSITIVE_SETTING_DEFAULTS.items():
        if flt(cfg.get(fieldname)) <= 0:
            updates[fieldname] = default

    for fieldname, default in DAY_SETTING_DEFAULTS.items():
        value = cint(cfg.get(fieldname))
        if value < 1 or value > 31:
            updates[fieldname] = default

    if cfg.get("vat_rate") in (None, ""):
        updates["vat_rate"] = 15

    # Zero is a legitimate explicit choice; repair only a missing value.
    if cfg.get("apply_buying_plan_adjustment") in (None, ""):
        updates["apply_buying_plan_adjustment"] = 1

    for fieldname, value in updates.items():
        frappe.db.set_single_value("Sales Forecast Settings", fieldname, value)


def _ensure_number_cards():
    if not frappe.db.exists("DocType", "Number Card"):
        return
    for name, method, document_type in NUMBER_CARDS:
        values = {
            "label": name,
            "type": "Custom",
            "method": method,
            "document_type": document_type,
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
            pass


def _detect_calendar_safely():
    try:
        from marina_custom_apps.sales_forecasting.services.common import detect_calendar_doctype

        detect_calendar_doctype()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sales Forecast Calendar Auto-Detection")
