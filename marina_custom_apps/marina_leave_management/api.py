"""Read-only Frappe API for paid-leave simulation; never creates allocations.

Employee access is explicitly restricted because leave history is sensitive.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate, today

from .accrual import simulate


def _can_view_employee(employee):
    user = frappe.session.user
    if user == "Administrator" or "HR Manager" in frappe.get_roles(user) or "System Manager" in frappe.get_roles(user):
        return True
    frappe.throw("HR Manager or System Manager role required", frappe.PermissionError)


def _read_leave_intervals(employee, joining, through):
    applications = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee,
            "leave_type": ["in", ["Paid Leave", "Leave Without Pay"]],
            "docstatus": 1,
            "status": "Approved",
            "from_date": ["<=", through],
            "to_date": [">=", joining],
        },
        fields=["name", "leave_type", "from_date", "to_date", "half_day",
                "half_day_date", "total_leave_days"],
        limit_page_length=0,
    )
    intervals, warnings = [], []
    for app in applications:
        start, end = getdate(app.from_date), getdate(app.to_date)
        actual_span = (end - start).days + 1
        # This version assumes each covered calendar day is a leave day unless
        # it is marked half-day. ERPNext holiday-list exclusions may differ.
        if app.half_day and app.half_day_date:
            half = getdate(app.half_day_date)
            if not start <= half <= end:
                warnings.append(f"{app.name}: half-day date is outside application range")
            day = start
            while day <= end:
                intervals.append({
                    "from_date": day, "to_date": day,
                    "fraction": "0.5" if day == half else "1",
                })
                day += timedelta(days=1)
        else:
            intervals.append({"from_date": start, "to_date": end})
        expected = Decimal(actual_span) - (Decimal("0.5") if app.half_day else Decimal("0"))
        if abs(Decimal(str(app.total_leave_days or 0)) - expected) > Decimal("0.0001"):
            warnings.append(
                f"{app.name}: application days {app.total_leave_days} differ from "
                f"calendar span {expected}; review holidays/leave rules before posting"
            )
    return intervals, warnings, len(applications)


@frappe.whitelist()
def preview_employee(employee: str, as_of: str | None = None):
    """Privileged simulation only; no ledger posting or DB writes."""
    _can_view_employee(employee)
    frappe.has_permission("Employee", "read", employee, throw=True)
    frappe.has_permission("Leave Application", "read", throw=True)
    cutoff = getdate(as_of or today())
    if cutoff > getdate(today()):
        frappe.throw("Future as_of dates are not supported in phase 1")
    row = frappe.db.get_value(
        "Employee", employee,
        ["name", "date_of_joining", "custom_leave_period", "status", "employment_type"],
        as_dict=True,
    )
    if not row or not row.date_of_joining:
        frappe.throw("Employee or joining date not found")
    if row.employment_type != "Full-time":
        frappe.throw("Phase 1 supports full-time employees only")
    if row.custom_leave_period not in ("Annual 21", "Annual 30"):
        frappe.throw("Employee must have Annual 21 or Annual 30 entitlement")
    joining = getdate(row.date_of_joining)
    intervals, warnings, counted = _read_leave_intervals(employee, joining, cutoff)
    result = simulate(joining, row.custom_leave_period, cutoff, intervals)
    result.update({
        "employee": row.name,
        "entitlement": row.custom_leave_period,
        "as_of": str(cutoff),
        "approved_absence_applications": counted,
        "warnings": warnings,
        "official_balance": False,
        "posting_enabled": False,
    })
    return result
