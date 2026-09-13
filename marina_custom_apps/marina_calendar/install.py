import json
from pathlib import Path

import frappe


NEW_DATE_DOCTYPE = "Marina Calendar Date"
NEW_EVENT_DOCTYPE = "Marina Calendar Event"
def after_install():
    _ensure_indexes()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def after_migrate():
    _ensure_indexes()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def _point_forecasting_to_marina_calendar():
    if not frappe.db.exists("DocType", "Sales Forecast Settings"):
        return
    if not frappe.db.exists("DocType", NEW_DATE_DOCTYPE):
        return
    frappe.db.set_single_value("Sales Forecast Settings", "calendar_doctype", NEW_DATE_DOCTYPE)


def _ensure_indexes():
    for doctype, fields, name in (
        (NEW_DATE_DOCTYPE, ["date"], "marina_calendar_date_idx"),
        (NEW_EVENT_DOCTYPE, ["start_date", "end_date"], "marina_calendar_event_range_idx"),
        (NEW_EVENT_DOCTYPE, ["scope", "branch", "city"], "marina_calendar_event_scope_idx"),
    ):
        if not frappe.db.exists("DocType", doctype):
            continue
        try:
            frappe.db.add_index(doctype, fields, index_name=name)
        except Exception:
            pass


def _sync_workspace():
    if not frappe.db.exists("DocType", "Workspace"):
        return
    path = Path(__file__).resolve().parent / "workspace" / "marina_calendar" / "marina_calendar.json"
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
