"""Read-only monthly accrual candidates. No allocation or ledger writes."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from .api import preview_employee

D = Decimal


def validate_credit_date(value):
    date_value = getdate(value)
    if date_value.day != 1:
        raise ValueError("Credit date must be the first day of a calendar month")
    if date_value > getdate(today()):
        raise ValueError("Future credit dates are not allowed in the preview")
    return date_value


def select_month_credit(simulation, credit_date):
    """Return just the earned credit due on a given first-of-month date.

    This is a total entitlement for that month, NOT an amount to post.
    """
    expected = str(credit_date)
    matches = [r for r in simulation.get("rows", [])
               if r.get("credit_date") == expected]
    if len(matches) > 1:
        raise ValueError("Multiple simulated credits for the same month")
    return matches[0] if matches else None


def _require_hr_access():
    user = frappe.session.user
    if user != "Administrator" and not {"HR Manager", "System Manager"}.intersection(
        frappe.get_roles(user)
    ):
        frappe.throw(_("HR Manager or System Manager required"), frappe.PermissionError)
    frappe.has_permission("Employee", ptype="read", throw=True)
    frappe.has_permission("Leave Application", ptype="read", throw=True)


def get_candidates(credit_date, employee=None, entitlement=None, include_exempt=False):
    """Generate candidate rows; leave allocations are never created.

    Existing overlapping allocations are a REVIEW flag, not automatically
    considered duplicates or offset against the monthly amount.
    """
    _require_hr_access()
    cutoff = validate_credit_date(credit_date)
    criteria = {
        "status": "Active",
        "employment_type": "Full-time",
        "custom_leave_period": ["in", ["Annual 21", "Annual 30"]],
    }
    if employee:
        criteria["name"] = employee
    if entitlement:
        if entitlement not in ("Annual 21", "Annual 30"):
            frappe.throw(_("Unsupported contract entitlement"))
        criteria["custom_leave_period"] = entitlement

    employees = frappe.get_list(
        "Employee", filters=criteria,
        fields=["name", "employee_name", "date_of_joining",
                "custom_leave_period", "custom_exclude_from_leave_accrual"],
        order_by="name", limit_page_length=0,
    )
    if not employees:
        return []

    # Batch read existing allocations rather than one DB request per employee.
    allocations = frappe.get_all(
        "Leave Allocation",
        filters={"employee": ["in", [x.name for x in employees]],
                 "leave_type": "Paid Leave", "docstatus": 1,
                 "from_date": ["<=", cutoff], "to_date": [">=", cutoff]},
        fields=["employee", "name"],
        limit_page_length=0,
    )
    overlap = {}
    for allocation in allocations:
        overlap.setdefault(allocation.employee, []).append(allocation.name)

    rows = []
    for emp in employees:
        excluded = cint(emp.custom_exclude_from_leave_accrual)
        if excluded and not include_exempt:
            continue
        row = {
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "entitlement": emp.custom_leave_period,
            "date_of_joining": emp.date_of_joining,
            "credit_date": str(cutoff),
            "period": str(cutoff - timedelta(days=1))[:7],
            "exempt": excluded,
            "candidate_credit": None,
            "status": "Review required",
            "notes": "",
        }
        if excluded:
            row["status"] = "Exempt"
            row["notes"] = "Excluded by Employee checkbox; no credit proposed"
            rows.append(row)
            continue
        if getdate(emp.date_of_joining) >= cutoff:
            row["status"] = "Not eligible yet"
            row["notes"] = "No completed eligible month before selected credit date"
            rows.append(row)
            continue
        try:
            calculation = preview_employee(emp.name, str(cutoff))
            month_row = select_month_credit(calculation, cutoff)
            if not month_row:
                row["status"] = "No accrual for date"
                row["notes"] = "No matching completed month"
                rows.append(row)
                continue
            amount = D(str(month_row["earned"]))
            row["candidate_credit"] = float(amount)
            row["excluded_days"] = float(D(str(month_row["excluded_calendar_days"])))
            notes = list(calculation.get("warnings", []))
            if overlap.get(emp.name):
                notes.append("Submitted allocation overlaps selected credit date: "
                             + ", ".join(overlap[emp.name][:3]))
            if amount <= 0:
                row["status"] = "Zero accrual"
            else:
                row["status"] = "Review required"
            if notes:
                row["status"] = "Review required" if amount > 0 else row["status"]
            row["notes"] = "; ".join(notes) if notes else (
                "Provisional amount; no posting enabled"
            )
        except Exception as exc:
            row["status"] = "Calculation error"
            row["notes"] = str(exc)[:240]
        rows.append(row)
    return rows
