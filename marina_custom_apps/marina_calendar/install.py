import hashlib
import json
from datetime import timedelta
from pathlib import Path

import frappe
from frappe.utils import getdate


NEW_DATE_DOCTYPE = "Marina Calendar Date"
NEW_EVENT_DOCTYPE = "Marina Calendar Event"
LEGACY_REQUIRED_FIELDS = {"date", "hijri_date", "hijri_m_name", "day", "month", "year"}
LEGACY_OPTIONAL_FIELDS = {"month_name", "week_day", "event"}


def after_install():
    _ensure_indexes()
    migrate_legacy_calendar()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def after_migrate():
    _ensure_indexes()
    migrate_legacy_calendar()
    _sync_workspace()
    _point_forecasting_to_marina_calendar()


def detect_legacy_calendar_doctype():
    if not frappe.db.exists("DocType", "DocType"):
        return None

    candidates = []
    for name in frappe.get_all(
        "DocType",
        filters={"custom": 1},
        pluck="name",
        limit_page_length=0,
    ):
        if name in {NEW_DATE_DOCTYPE, NEW_EVENT_DOCTYPE, "Marina Calendar Date Event"}:
            continue
        try:
            fields = {f.fieldname for f in frappe.get_meta(name).fields}
        except Exception:
            continue
        if LEGACY_REQUIRED_FIELDS.issubset(fields):
            score = len(LEGACY_REQUIRED_FIELDS & fields) + len(LEGACY_OPTIONAL_FIELDS & fields)
            candidates.append((score, name))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1] if candidates else None


def migrate_legacy_calendar():
    if not frappe.db.exists("DocType", NEW_DATE_DOCTYPE):
        return {"migrated": False, "reason": "New calendar DocType not installed"}

    legacy = detect_legacy_calendar_doctype()
    if not legacy:
        return {"migrated": False, "reason": "No legacy custom calendar detected"}

    meta_fields = {f.fieldname for f in frappe.get_meta(legacy).fields}
    fields = ["name", "date", "hijri_date", "hijri_m_name", "day", "month", "year"]
    for optional in ("month_name", "week_day", "event"):
        if optional in meta_fields:
            fields.append(optional)

    rows = frappe.get_all(
        legacy,
        fields=fields,
        order_by="date asc",
        limit_page_length=0,
    )

    date_count = 0
    for row in rows:
        if not row.date:
            continue
        name = str(getdate(row.date))
        values = {
            "date": name,
            "hijri_date": row.get("hijri_date") or "",
            "hijri_m_name": row.get("hijri_m_name") or "",
            "day": row.get("day") or 0,
            "month": row.get("month") or 0,
            "year": row.get("year") or 0,
            "legacy_source_doctype": legacy,
            "legacy_source_name": row.name,
            "legacy_event": row.get("event") or "",
        }
        if frappe.db.exists(NEW_DATE_DOCTYPE, name):
            doc = frappe.get_doc(NEW_DATE_DOCTYPE, name)
            changed = False
            for field in ("hijri_date", "hijri_m_name", "day", "month", "year", "legacy_source_doctype", "legacy_source_name", "legacy_event"):
                if not doc.get(field) and values.get(field):
                    doc.set(field, values.get(field))
                    changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            frappe.get_doc({"doctype": NEW_DATE_DOCTYPE, **values}).insert(ignore_permissions=True)
        date_count += 1

    event_count = _migrate_legacy_events(legacy, rows) if "event" in meta_fields else 0
    return {
        "migrated": True,
        "legacy_doctype": legacy,
        "calendar_dates": date_count,
        "calendar_events_created": event_count,
    }


def _migrate_legacy_events(legacy_doctype, rows):
    sequences = []
    current = None

    for row in rows:
        text = (row.get("event") or "").strip()
        if not text or not row.date:
            if current:
                sequences.append(current)
                current = None
            continue

        day = getdate(row.date)
        if current and current["event_name"] == text and day == current["end_date"] + timedelta(days=1):
            current["end_date"] = day
            continue

        if current:
            sequences.append(current)
        current = {"event_name": text, "start_date": day, "end_date": day}

    if current:
        sequences.append(current)

    created = 0
    for seq in sequences:
        raw = f"{legacy_doctype}|{seq['event_name']}|{seq['start_date']}|{seq['end_date']}"
        legacy_key = "legacy-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()
        if frappe.db.exists(NEW_EVENT_DOCTYPE, {"legacy_key": legacy_key}):
            continue

        frappe.get_doc({
            "doctype": NEW_EVENT_DOCTYPE,
            "event_name": seq["event_name"],
            "event_type": "Other",
            "start_date": str(seq["start_date"]),
            "end_date": str(seq["end_date"]),
            "all_day": 1,
            "importance": "Medium",
            "expected_sales_impact": "Unknown",
            "impact_strength": "Medium",
            "forecast_relevant": 1,
            "scope": "Company",
            "company": "Marina" if frappe.db.exists("Company", "Marina") else "",
            "source": f"Imported from {legacy_doctype}.event",
            "legacy_key": legacy_key,
        }).insert(ignore_permissions=True)
        created += 1

    return created


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
