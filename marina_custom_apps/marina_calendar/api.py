import json

import frappe
from frappe import _


@frappe.whitelist()
def get_calendar_events(doctype, start, end, field_map, filters=None, fields=None):
    """Return active Marina events for Frappe's Calendar view.

    The calendar keeps the normal Frappe filter bar, so filters such as Event Type,
    Scope, Branch and Sales Impact are applied server-side with user permissions.
    Disabled events are always hidden.
    """
    from frappe.desk.calendar import get_events

    parsed_filters = frappe.parse_json(filters) if filters else []
    parsed_filters = parsed_filters or []
    parsed_filters.append(["Marina Calendar Event", "disabled", "=", 0])

    events = get_events(
        doctype="Marina Calendar Event",
        start=start,
        end=end,
        field_map=field_map,
        filters=json.dumps(parsed_filters),
        fields=fields,
    )

    for event in events:
        scope = event.get("scope") or "Company"
        scope_value = (
            event.get("branch")
            if scope == "Branch"
            else event.get("city")
            if scope == "City"
            else event.get("company")
        )

        original_title = event.get("event_name") or ""
        if scope_value and scope != "Company":
            event["event_name"] = f"[{scope_value}] {original_title}"

        details = [
            event.get("event_type"),
            event.get("expected_sales_impact"),
            event.get("store_trading_status"),
        ]
        if scope_value:
            details.append(f"{scope}: {scope_value}")
        event["tooltip"] = " | ".join([str(value) for value in details if value and value != "No Change"])

    return events


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
