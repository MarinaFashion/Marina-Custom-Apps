from datetime import timedelta

import frappe
from frappe.utils import getdate


def iter_dates(start_date, end_date):
    current = getdate(start_date)
    end = getdate(end_date)
    while current <= end:
        yield current
        current += timedelta(days=1)


def ensure_calendar_date(date_value):
    name = str(getdate(date_value))
    if frappe.db.exists("Marina Calendar Date", name):
        return frappe.get_doc("Marina Calendar Date", name)

    doc = frappe.get_doc({
        "doctype": "Marina Calendar Date",
        "date": name,
    })
    doc.insert(ignore_permissions=True)
    return doc


def event_row_values(event):
    return {
        "calendar_event": event.name,
        "event_name": event.event_name,
        "event_type": event.event_type,
        "importance": event.importance,
        "expected_sales_impact": event.expected_sales_impact,
        "impact_strength": event.impact_strength,
        "store_trading_status": event.store_trading_status or "No Change",
        "forecast_relevant": event.forecast_relevant,
        "scope": event.scope,
        "company": event.company,
        "city": event.city,
        "branch": event.branch,
        "main_group": event.main_group,
    }


def sync_event_dates(event_name):
    event = frappe.get_doc("Marina Calendar Event", event_name)
    old_parents = set(frappe.get_all(
        "Marina Calendar Date Event",
        filters={"calendar_event": event.name},
        pluck="parent",
        limit_page_length=0,
    ))

    frappe.db.delete("Marina Calendar Date Event", {"calendar_event": event.name})

    new_parents = set()
    if not event.disabled:
        for day in iter_dates(event.start_date, event.end_date or event.start_date):
            date_doc = ensure_calendar_date(day)
            date_doc.reload()
            date_doc.append("events", event_row_values(event))
            date_doc.save(ignore_permissions=True)
            new_parents.add(date_doc.name)

    for parent in old_parents - new_parents:
        if frappe.db.exists("Marina Calendar Date", parent):
            doc = frappe.get_doc("Marina Calendar Date", parent)
            doc.save(ignore_permissions=True)

    return len(new_parents)


def remove_event_links(event_name):
    parents = set(frappe.get_all(
        "Marina Calendar Date Event",
        filters={"calendar_event": event_name},
        pluck="parent",
        limit_page_length=0,
    ))
    frappe.db.delete("Marina Calendar Date Event", {"calendar_event": event_name})
    for parent in parents:
        if frappe.db.exists("Marina Calendar Date", parent):
            doc = frappe.get_doc("Marina Calendar Date", parent)
            doc.save(ignore_permissions=True)


def rebuild_all_event_links():
    frappe.db.delete("Marina Calendar Date Event", {})
    for name in frappe.get_all(
        "Marina Calendar Event",
        filters={"disabled": 0},
        pluck="name",
        order_by="start_date asc, name asc",
        limit_page_length=0,
    ):
        sync_event_dates(name)
