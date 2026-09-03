import frappe
from frappe import _


@frappe.whitelist()
def rebuild_event_links():
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("System Manager role required."), frappe.PermissionError)
    from marina_custom_apps.marina_calendar.services import rebuild_all_event_links
    rebuild_all_event_links()
    return {"success": True}


@frappe.whitelist()
def create_event_for_date(calendar_date):
    doc = frappe.get_doc("Marina Calendar Date", calendar_date)
    doc.check_permission("read")
    event = frappe.new_doc("Marina Calendar Event")
    event.start_date = doc.date
    event.end_date = doc.date
    event.scope = "Company"
    return event.as_dict()


@frappe.whitelist()
def get_migration_status():
    from marina_custom_apps.marina_calendar.install import detect_legacy_calendar_doctype

    legacy = detect_legacy_calendar_doctype()
    legacy_rows = 0
    if legacy:
        legacy_rows = frappe.db.count(legacy)

    return {
        "legacy_doctype": legacy,
        "legacy_rows": legacy_rows,
        "marina_calendar_dates": frappe.db.count("Marina Calendar Date") if frappe.db.exists("DocType", "Marina Calendar Date") else 0,
        "marina_calendar_events": frappe.db.count("Marina Calendar Event") if frappe.db.exists("DocType", "Marina Calendar Event") else 0,
        "date_event_links": frappe.db.count("Marina Calendar Date Event") if frappe.db.exists("DocType", "Marina Calendar Date Event") else 0,
        "forecast_calendar_doctype": frappe.db.get_single_value("Sales Forecast Settings", "calendar_doctype") if frappe.db.exists("DocType", "Sales Forecast Settings") else None,
    }
