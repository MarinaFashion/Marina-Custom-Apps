"""Read-only HRMS posting preflight for a single employee/month.

This module deliberately exposes NO posting implementation. Preflight is a
safety gate for design and validation, not permission to create allocations.
"""
from __future__ import annotations

import calendar
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate

from marina_custom_apps.marina_custom_apps.doctype.marina_leave_accrual_batch.marina_leave_accrual_batch import (
    BATCH, require_hr_manager, _candidate_rows, canonical,
)

ALLOCATION = "Leave Allocation"
LEDGER = "Leave Ledger Entry"
LEAVE_TYPE = "Paid Leave"


def _row_snapshot(batch, employee):
    matching = [r for r in batch.employees if r.employee == employee]
    if len(matching) != 1:
        frappe.throw(_("Employee must appear exactly once in the approved batch"))
    return matching[0]


def _review(batch, employee):
    if batch.status != "Approved":
        frappe.throw(_("Batch must be Approved before posting preflight"))
    saved = _row_snapshot(batch, employee)
    current_rows = _candidate_rows(batch)
    current = [r for r in current_rows if r["employee"] == employee]
    if len(current) != 1 or canonical(current[0]) != saved.calculation_signature:
        frappe.throw(_("Accrual changed since approval; investigate before posting"))
    return saved, current[0]


def _ledger_scope(employee, credit_date):
    # The month-end date is an effective date, NOT the creation timestamp.
    # Search all allocation ledger entries for this employee: earlier period
    # allocations may still overlap or have backdated manual credits.
    allocations = frappe.get_all(
        ALLOCATION,
        filters={"employee": employee, "leave_type": LEAVE_TYPE,
                 "docstatus": ["<", 2]},
        fields=["name", "docstatus", "from_date", "to_date",
                "new_leaves_allocated"],
        limit_page_length=0,
    )
    linked = frappe.get_all(
        LEDGER,
        filters={"employee": employee, "leave_type": LEAVE_TYPE,
                 "transaction_type": ALLOCATION, "docstatus": 1},
        fields=["name", "transaction_name", "from_date", "to_date", "leaves"],
        limit_page_length=0,
    )
    overlaps = []
    for allocation in allocations:
        if getdate(allocation.from_date) <= credit_date <= getdate(allocation.to_date):
            overlaps.append(allocation.name)
    return allocations, linked, overlaps


def analyze(batch, employee):
    saved, current = _review(batch, employee)
    credit_date = getdate(batch.credit_date)
    if credit_date.day != calendar.monthrange(credit_date.year, credit_date.month)[1]:
        frappe.throw(_("Only calendar month-end dates are supported"))
    leave_type = frappe.db.get_value(
        "Leave Type", LEAVE_TYPE,
        ["is_earned_leave", "earned_leave_frequency", "is_carry_forward",
         "rounding", "max_leaves_allowed"],
        as_dict=True,
    )
    if not leave_type:
        frappe.throw(_("Paid Leave type does not exist"))

    employee_details = frappe.db.get_value(
        "Employee", employee,
        ["name", "company", "status", "employment_type",
         "custom_exclude_from_leave_accrual", "custom_leave_period"],
        as_dict=True,
    )
    if not employee_details or employee_details.company != batch.company:
        frappe.throw(_("Employee and company mismatch"))

    allocations, ledger, overlaps = _ledger_scope(employee, credit_date)
    blockers = []
    warnings = []
    amount = Decimal(str(saved.candidate_credit or "0"))
    if amount <= 0:
        blockers.append("Zero or negative monthly credit")
    if current["status"] != "Ready for Approval":
        blockers.append("Current candidate is not Ready for Approval")
    if employee_details.custom_exclude_from_leave_accrual:
        blockers.append("Employee is exempt")
    if employee_details.status != "Active" or employee_details.employment_type != "Full-time":
        blockers.append("Employee is not an active full-time employee")
    if int(leave_type.is_earned_leave or 0):
        blockers.append(
            "Paid Leave is configured as ERPNext earned leave; native scheduled allocation may duplicate Marina credits"
        )
    if overlaps:
        blockers.append(
            "Existing allocation period overlaps month-end: " + ", ".join(overlaps[:8])
        )
    if allocations:
        warnings.append(
            f"{len(allocations)} existing submitted/draft Paid Leave allocation(s) for employee; inspect allocation windows and historical cutover"
        )
    if ledger:
        warnings.append(
            f"{len(ledger)} submitted Paid Leave allocation-ledger entry/entries exist; require reference reconciliation"
        )
    # No custom employee-month posting reference DocType exists yet.
    blockers.append("Employee/month posting journal and idempotency key not yet installed")
    blockers.append("Historical opening balance cutover not yet authorized")
    blockers.append("HRMS fractional Leave Allocation behavior not yet verified in demo")
    return {
        "batch": batch.name,
        "employee": employee,
        "company": batch.company,
        "credit_date": str(credit_date),
        "monthly_credit": float(amount),
        "leave_type": LEAVE_TYPE,
        "leave_type_is_earned": bool(leave_type.is_earned_leave),
        "earned_leave_frequency": leave_type.earned_leave_frequency,
        "carry_forward": bool(leave_type.is_carry_forward),
        "rounding": leave_type.rounding,
        "max_leaves_allowed": leave_type.max_leaves_allowed,
        "allocation_count": len(allocations),
        "allocation_ledger_count": len(ledger),
        "overlapping_allocations": overlaps,
        "blocking_reasons": blockers,
        "warnings": warnings,
        "posting_enabled": False,
        "would_create_leave_allocation": False,
        "would_create_ledger_entry": False,
    }


@frappe.whitelist()
def preview_employee_posting(batch_name, employee):
    """Read-only diagnostic with HR role and batch document permission checks."""
    require_hr_manager()
    batch = frappe.get_doc(BATCH, batch_name)
    batch.check_permission("read")
    frappe.has_permission("Employee", "read", employee, throw=True)
    frappe.has_permission(ALLOCATION, "read", throw=True)
    frappe.has_permission(LEDGER, "read", throw=True)
    return analyze(batch, employee)
