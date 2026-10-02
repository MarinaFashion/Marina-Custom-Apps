from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate


def _value(row, fieldname):
    if hasattr(row, "get"):
        return row.get(fieldname)
    return getattr(row, fieldname, None)


def validate_location_periods(rows):
    periods = []

    for idx, row in enumerate(rows or [], start=1):
        pos_profile = _value(row, "pos_profile")
        from_date = _value(row, "from_date")
        to_date = _value(row, "to_date")

        if not pos_profile or not from_date:
            frappe.throw(_("Location row {0}: Location and From Date are required.").format(idx))

        start = getdate(from_date)
        end = getdate(to_date) if to_date else None
        if end and end < start:
            frappe.throw(_("Location row {0}: To Date cannot be before From Date.").format(idx))

        periods.append(
            {
                "row": idx,
                "pos_profile": pos_profile,
                "from_date": start,
                "to_date": end,
            }
        )

    periods.sort(key=lambda row: row["from_date"])

    for previous, current in zip(periods, periods[1:]):
        if previous["to_date"] is None or current["from_date"] <= previous["to_date"]:
            frappe.throw(
                _(
                    "Terminal location periods overlap between rows {0} and {1}. "
                    "Each transaction date must resolve to one location only."
                ).format(previous["row"], current["row"])
            )

    return periods


def select_pos_profile(periods, transaction_date):
    if not transaction_date:
        return None

    target_date = getdate(transaction_date)
    matches = []

    for row in periods or []:
        from_date = _value(row, "from_date")
        if not from_date:
            continue
        start = getdate(from_date)
        to_date = _value(row, "to_date")
        end = getdate(to_date) if to_date else None

        if start <= target_date and (end is None or target_date <= end):
            matches.append(_value(row, "pos_profile"))

    matches = [value for value in matches if value]
    if len(matches) > 1:
        frappe.throw(_("More than one terminal location matches transaction date {0}.").format(target_date))

    return matches[0] if matches else None


def get_terminal_periods(terminal_id):
    terminal_id = str(terminal_id or "").strip()
    if not terminal_id:
        return []

    cache = getattr(frappe.local, "marina_terminal_location_periods", None)
    if cache is None:
        cache = {}
        frappe.local.marina_terminal_location_periods = cache

    if terminal_id in cache:
        return cache[terminal_id]

    terminal_name = frappe.db.get_value(
        "Terminal Reference",
        {"terminal_id": terminal_id},
        "name",
    )
    if not terminal_name:
        cache[terminal_id] = []
        return []

    periods = frappe.get_all(
        "Terminal Location History",
        filters={
            "parent": terminal_name,
            "parenttype": "Terminal Reference",
            "parentfield": "locations",
        },
        fields=["pos_profile", "from_date", "to_date"],
        order_by="from_date asc, idx asc",
        limit_page_length=0,
    )
    cache[terminal_id] = periods
    return periods


def resolve_pos_profile(terminal_id, transaction_date):
    return select_pos_profile(get_terminal_periods(terminal_id), transaction_date)


def clear_terminal_period_cache(terminal_id=None):
    cache = getattr(frappe.local, "marina_terminal_location_periods", None)
    if not cache:
        return
    if terminal_id:
        cache.pop(str(terminal_id).strip(), None)
    else:
        cache.clear()
