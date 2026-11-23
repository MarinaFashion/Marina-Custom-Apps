"""Read-only paid-leave accrual reconciliation (HR review only).

Provisional estimates are NOT ERPNext leave balances or approved allocations.
No document creation, modification, or DB transaction is performed here.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from marina_custom_apps.marina_leave_management.api import preview_employee

D = Decimal
TEST_ALLOCATIONS = {"HR-LAL-2024-00001"}


def dec(value):
    return D(str(value or 0))


def rounded(value):
    return float(value.quantize(D("0.000001")))


def get_columns():
    columns = [
        ("employee", "Employee", "Link", "Employee", 145),
        ("employee_name", "Employee Name", "Data", None, 175),
        ("date_of_joining", "Joining Date", "Date", None, 105),
        ("entitlement", "Entitlement", "Data", None, 110),
        ("exempt", "Exempt", "Check", None, 75),
        ("simulated_earned", "Simulated Earned Days", "Float", None, 155),
        ("excluded_days", "Excluded Days", "Float", None, 125),
        ("ledger_credits", "Existing Credit Entries", "Float", None, 155),
        ("ledger_usage", "Posted Leave Debits", "Float", None, 150),
        ("indicative_balance", "Indicative Balance", "Float", None, 140),
        ("unposted_credit", "Provisional Unposted Credit", "Float", None, 190),
        ("applications", "Exclusion Applications", "Int", None, 155),
        ("review_status", "Review Status", "Data", None, 175),
        ("warnings", "Review Notes", "Small Text", None, 420),
    ]
    return [
        dict(fieldname=key, label=_(label), fieldtype=typ,
             options=options, width=width, **({"precision": 6} if typ == "Float" else {}))
        for key, label, typ, options, width in columns
    ]


def ledger_snapshot(employee_ids, cutoff):
    """Aggregate submitted Paid Leave ledger, omitting future/spanning entries.

    Ledger time slicing is only approximate; applications spanning the
    cutoff are flagged for review rather than partially debited by guesswork.
    """
    result = defaultdict(lambda: {
        "credit": D("0"), "debit": D("0"), "future": 0,
        "spanning": 0, "other": 0, "test": 0,
    })
    if not employee_ids:
        return result
    entries = frappe.get_all(
        "Leave Ledger Entry",
        filters={"employee": ["in", employee_ids],
                 "leave_type": "Paid Leave", "docstatus": 1},
        fields=["employee", "transaction_type", "transaction_name",
                "from_date", "to_date", "leaves"],
        limit_page_length=0,
    )
    for entry in entries:
        info = result[entry.employee]
        if entry.transaction_type == "Leave Allocation" and entry.transaction_name in TEST_ALLOCATIONS:
            info["test"] += 1
            continue
        start = getdate(entry.from_date or entry.to_date)
        end = getdate(entry.to_date or entry.from_date)
        if start > cutoff:
            info["future"] += 1
            continue
        days = dec(entry.leaves)
        if entry.transaction_type == "Leave Allocation":
            # Allocation periods frequently end after the report date.
            # Use effective start date, not allocation end date.
            info["credit"] += days
        elif entry.transaction_type == "Leave Application":
            if end > cutoff:
                info["spanning"] += 1
                continue
            info["debit"] += days
        else:
            info["other"] += 1
    return result


def execute(filters=None):
    filters = frappe._dict(filters or {})
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if not (user == "Administrator" or roles.intersection({"HR Manager", "System Manager"})):
        frappe.throw(_("Only HR Manager or System Manager can view this report"), frappe.PermissionError)
    frappe.has_permission("Employee", ptype="read", throw=True)
    frappe.has_permission("Leave Application", ptype="read", throw=True)

    cutoff = getdate(filters.get("as_of") or today())
    if cutoff > getdate(today()):
        frappe.throw(_("Future dates are not supported in preview mode"))
    criteria = {
        "status": "Active",
        "employment_type": "Full-time",
        "custom_leave_period": ["in", ["Annual 21", "Annual 30"]],
    }
    if filters.get("employee"):
        criteria["name"] = filters.employee
    if filters.get("entitlement"):
        criteria["custom_leave_period"] = filters.entitlement

    employees = frappe.get_list(
        "Employee", filters=criteria,
        fields=["name", "employee_name", "date_of_joining",
                "custom_leave_period", "custom_exclude_from_leave_accrual"],
        order_by="name", limit_page_length=0,
    )
    ledger = ledger_snapshot([e.name for e in employees], cutoff)
    rows = []
    for employee in employees:
        exempt = cint(employee.custom_exclude_from_leave_accrual)
        if exempt and not cint(filters.get("include_exempt", 1)):
            continue
        row = {
            "employee": employee.name,
            "employee_name": employee.employee_name,
            "date_of_joining": employee.date_of_joining,
            "entitlement": employee.custom_leave_period,
            "exempt": exempt,
        }
        if exempt:
            row.update({
                "review_status": "Exempt",
                "warnings": "HR exemption; no entitlement or correction proposed.",
            })
            rows.append(row)
            continue
        try:
            preview = preview_employee(employee.name, str(cutoff))
            info = ledger[employee.name]
            earned = dec(preview["earned"])
            credit = info["credit"]
            debit = info["debit"]
            warnings = list(preview["warnings"])
            if info["test"]:
                warnings.append(f"{info['test']} test allocation ledger entries ignored")
            if info["future"]:
                warnings.append(f"{info['future']} future ledger entries omitted")
            if info["spanning"]:
                warnings.append(f"{info['spanning']} date-spanning ledger entries omitted")
            if info["other"]:
                warnings.append(f"{info['other']} unrecognized ledger sources")
            if getdate(employee.date_of_joining) < getdate("2024-01-01"):
                warnings.append("Long tenure: verify earlier records and contract history")
            row.update({
                "simulated_earned": rounded(earned),
                "excluded_days": rounded(dec(preview["excluded_days"])),
                "ledger_credits": rounded(credit),
                "ledger_usage": rounded(debit),
                # Illustrative historical earned less posted consumption, not
                # the real per-allocation-period HRMS balance.
                "indicative_balance": rounded(earned + debit),
                "unposted_credit": rounded(earned - credit),
                "applications": preview["approved_absence_applications"],
                "review_status": "Review required",
                "warnings": "; ".join(warnings) if warnings else
                    "Provisional only: reconcile historical policy before approving",
            })
        except Exception as exc:
            row.update({
                "review_status": "Calculation error",
                "warnings": str(exc)[:240],
            })
        rows.append(row)
    return get_columns(), rows
