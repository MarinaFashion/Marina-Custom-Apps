import json
from pathlib import Path

import frappe


NEW_DATE_DOCTYPE = "Marina Calendar Date"
NEW_EVENT_DOCTYPE = "Marina Calendar Event"


def after_install():
    _repair_calendar_date_metadata()
    _ensure_indexes()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def after_migrate():
    _repair_calendar_date_metadata()
    _ensure_indexes()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def _repair_calendar_date_metadata():
    """Keep bulk import enabled and remove the obsolete Date-unique metadata.

    Marina Calendar Date already uses the Gregorian date as its document name,
    and its controller rejects duplicate dates. Frappe v15 does not allow a
    Date field to carry the DocField unique flag when Customize Form is saved.
    """
    if not frappe.db.exists("DocType", NEW_DATE_DOCTYPE):
        return

    frappe.db.set_value(
        "DocType",
        NEW_DATE_DOCTYPE,
        {
            "allow_import": 1,
            # The controller's autoname() method already uses the Gregorian
            # date. Keeping ``field:date`` here makes Frappe v15 force the
            # Date DocField to unique=1 every time Customize Form is saved,
            # then reject it because Date is not a supported unique type.
            "autoname": "",
        },
        update_modified=False,
    )

    date_field = frappe.db.exists(
        "DocField",
        {
            "parent": NEW_DATE_DOCTYPE,
            "parenttype": "DocType",
            "fieldname": "date",
        },
    )
    if date_field:
        frappe.db.set_value(
            "DocField",
            date_field,
            "unique",
            0,
            update_modified=False,
        )

    if frappe.db.exists("DocType", "Property Setter"):
        frappe.db.delete(
            "Property Setter",
            {
                "doc_type": NEW_DATE_DOCTYPE,
                "field_name": "date",
                "property": "unique",
            },
        )

    frappe.clear_cache(doctype=NEW_DATE_DOCTYPE)


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
