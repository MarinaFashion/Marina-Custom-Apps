"""Phase 4C: manual, DEMO-ONLY single-employee Paid Leave allocation pilot.

No background jobs, no batch-wide posting, no production entrypoint.
The journal and HRMS allocation are committed in the same request transaction.
"""
from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, now_datetime

from marina_custom_apps.marina_custom_apps.doctype.marina_leave_accrual_batch.marina_leave_accrual_batch import (
    BATCH, require_hr_manager,
)
from marina_custom_apps.marina_leave_management.posting_preflight import (
    _review, _ledger_scope, LEAVE_TYPE,
)
from marina_custom_apps.marina_leave_management.precision import (
    calculate_posting, posting_key,
)

JOURNAL = "Marina Leave Posting Journal"
SETTINGS = "Marina Leave Management Settings"


def _assert_demo():
    if not frappe.local.site.endswith("demo.frappe.cloud"):
        frappe.throw(_("Leave posting pilot is allowed on the Marina demo site only"))


def _settings(batch, employee, require_enabled):
    config = frappe.get_single(SETTINGS)
    if require_enabled and not cint(config.enable_leave_posting):
        frappe.throw(_("Enable Leave Posting is OFF"))
    if not config.pilot_employee or employee != config.pilot_employee:
        frappe.throw(_("Only the configured pilot employee can be posted"))
    if not config.cutover_confirmed or not config.cutover_date or not config.allocation_end_date:
        frappe.throw(_("Historical balance cutover, start and end dates must be approved"))
    if getdate(batch.credit_date) < getdate(config.cutover_date):
        frappe.throw(_("Batch month is earlier than the approved cutover date"))
    if getdate(batch.credit_date) > getdate(config.allocation_end_date):
        frappe.throw(_("Batch month is later than the configured allocation end date"))
    if frappe.db.get_value("Leave Type", LEAVE_TYPE, "is_earned_leave"):
        frappe.throw(_("Native Paid Leave earned leave must remain disabled"))
    if cint(frappe.db.get_value("Leave Type", LEAVE_TYPE, "allow_over_allocation")):
        frappe.throw(_("Pilot requires over-allocation disabled until separately audited"))
    return config


def _posted_history(employee, batch):
    return frappe.get_all(
        JOURNAL,
        filters={"employee": employee, "company": batch.company,
                 "leave_type": LEAVE_TYPE, "status": "Posted"},
        fields=["name", "credit_date", "closing_residual", "leave_allocation"],
        order_by="credit_date asc",
        limit_page_length=0,
    )


def _plan(batch, employee, require_enabled=True):
    _assert_demo()
    config = _settings(batch, employee, require_enabled=require_enabled)
    saved, current = _review(batch, employee)
    if current["status"] != "Ready for Approval":
        frappe.throw(_("Pilot only permits Ready for Approval employees"))
    if Decimal(str(saved.candidate_credit or 0)) <= 0:
        frappe.throw(_("Pilot does not post zero credit"))
    if frappe.db.get_value("Employee", employee, "company") != batch.company:
        frappe.throw(_("Employee company mismatch"))
    if frappe.db.get_value("Employee", employee, "status") != "Active":
        frappe.throw(_("Employee must be active"))
    if frappe.db.get_value("Employee", employee, "employment_type") != "Full-time":
        frappe.throw(_("Employee must be full-time"))
    if frappe.db.get_value("Employee", employee, "custom_exclude_from_leave_accrual"):
        frappe.throw(_("Employee is excluded from accrual"))

    key = posting_key(batch.company, employee, LEAVE_TYPE, batch.credit_date)
    if frappe.db.exists(JOURNAL, key):
        frappe.throw(_("Employee/month already has a posting journal: {0}").format(key))

    history = _posted_history(employee, batch)
    credit_date = getdate(batch.credit_date)
    if history:
        last = history[-1]
        if getdate(last.credit_date) >= credit_date:
            frappe.throw(_("Cannot post out of chronological order"))
        expected_next = getdate(add_months(last.credit_date, 1))
        if expected_next != credit_date:
            frappe.throw(_("Post every completed month sequentially after cutover"))
        if len({r.leave_allocation for r in history}) != 1:
            frappe.throw(_("Pilot has multiple allocation references; inspect manually"))
        allocation = frappe.get_doc("Leave Allocation", last.leave_allocation)
        if allocation.docstatus != 1:
            frappe.throw(_("Linked allocation is not submitted"))
        if allocation.employee != employee or allocation.leave_type != LEAVE_TYPE:
            frappe.throw(_("Linked allocation employee/leave type mismatch"))
        if allocation.company != batch.company:
            frappe.throw(_("Linked allocation company mismatch"))
        other_allocations = frappe.get_all(
            "Leave Allocation",
            filters={"employee": employee, "leave_type": LEAVE_TYPE,
                     "docstatus": ["<", 2], "name": ["!=", allocation.name]},
            pluck="name", limit_page_length=1,
        )
        if other_allocations:
            frappe.throw(_("Other Paid Leave allocations detected; manual reconciliation required"))
        ledger_total = Decimal(str(allocation.get_existing_leave_count() or 0))
        journal_total = sum(
            (Decimal(str(frappe.db.get_value(JOURNAL, r.name, "hrms_credit") or "0"))
             for r in history), Decimal("0")
        )
        if abs(ledger_total - journal_total) > Decimal("0.000001"):
            frappe.throw(_("Allocation ledger credits differ from posted Marina journal history"))
        if getdate(allocation.from_date) != getdate(config.cutover_date):
            frappe.throw(_("Allocation start differs from pilot cutover"))
        if getdate(allocation.to_date) != getdate(config.allocation_end_date):
            frappe.throw(_("Allocation validity changed after previous posting"))
        if cint(allocation.carry_forward):
            frappe.throw(_("Pilot allocation must not use carry forward"))
        allocation_name = allocation.name
        residual = last.closing_residual
    else:
        if credit_date != getdate(config.cutover_date):
            frappe.throw(_("First pilot posting must equal the approved cutover month"))
        allocations, ledgers, overlaps = _ledger_scope(employee, credit_date)
        if allocations or ledgers or overlaps:
            frappe.throw(_("Pilot employee has Paid Leave allocations/credits; historical reconciliation required"))
        allocation_name = None
        residual = "0"

    figures = calculate_posting(saved.candidate_credit, residual)
    if Decimal(figures["hrms_credit"]) <= 0:
        frappe.throw(_("Calculated HRMS credit is not positive"))
    return {
        "batch": batch.name, "company": batch.company, "employee": employee,
        "credit_date": str(credit_date), "posting_key": key,
        "leave_allocation": allocation_name, "allocation_end_date": str(config.allocation_end_date),
        "allocation_from_date": str(config.cutover_date),
        "action": "Update submitted allocation" if allocation_name else "Create submitted allocation",
        **figures,
    }


def _access(batch_name, employee, require_write=False):
    require_hr_manager()
    frappe.has_permission("Employee", "read", employee, throw=True)
    frappe.has_permission("Leave Allocation", "read", throw=True)
    if require_write:
        frappe.has_permission("Leave Allocation", "create", throw=True)
        frappe.has_permission("Leave Allocation", "submit", throw=True)
    batch = frappe.get_doc(BATCH, batch_name)
    batch.check_permission("read")
    if batch.status != "Approved":
        frappe.throw(_("Batch must be Approved"))
    return batch


@frappe.whitelist()
def dry_run_selected_employee(batch_name, employee):
    """Read-only pilot posting plan. Also requires explicit pilot configuration."""
    _assert_demo()
    batch = _access(batch_name, employee)
    result = _plan(batch, employee, require_enabled=False)
    return {**result, "dry_run": True, "database_changes": False}


@frappe.whitelist(methods=["POST"])
def post_selected_employee(batch_name, employee, confirm=0):
    """ONE pilot employee, fully atomic; no implicit commit or scheduler."""
    _assert_demo()
    if not cint(confirm):
        frappe.throw(_("Explicit posting confirmation is required"))
    batch = _access(batch_name, employee, require_write=True)
    # This serializes concurrent posting attempts for this employee, even
    # when they originate from different monthly batch documents.
    frappe.db.sql("SELECT name FROM `tabEmployee` WHERE name=%s FOR UPDATE", (employee,))
    frappe.db.sql(
        "SELECT name FROM `tabMarina Leave Accrual Batch` WHERE name=%s FOR UPDATE",
        (batch_name,),
    )
    plan = _plan(batch, employee, require_enabled=True)
    frappe.db.savepoint("marina_single_employee_post")
    try:
        journal = frappe.get_doc({
            "doctype": JOURNAL,
            "posting_key": plan["posting_key"],
            "company": batch.company,
            "employee": employee,
            "leave_type": LEAVE_TYPE,
            "credit_date": batch.credit_date,
            "batch": batch.name,
            "status": "Pending",
            "exact_credit": plan["exact_credit"],
            "opening_residual": plan["opening_residual"],
            "hrms_credit": plan["hrms_credit"],
            "closing_residual": plan["closing_residual"],
            "approved_by": frappe.session.user,
        })
        journal.flags.marina_authorized_posting_service = True
        journal.insert(ignore_permissions=True)

        if plan["leave_allocation"]:
            allocation = frappe.get_doc("Leave Allocation", plan["leave_allocation"])
            old_credited = Decimal(str(allocation.get_existing_leave_count() or 0))
            allocation.new_leaves_allocated = float(
                old_credited + Decimal(plan["hrms_credit"])
            )
            allocation.flags.ignore_permissions = True
            allocation.save(ignore_permissions=True)
        else:
            allocation = frappe.get_doc({
                "doctype": "Leave Allocation",
                "employee": employee,
                "company": batch.company,
                "leave_type": LEAVE_TYPE,
                "from_date": batch.credit_date,
                "to_date": plan["allocation_end_date"],
                "new_leaves_allocated": float(Decimal(plan["hrms_credit"])),
                "carry_forward": 0,
            })
            allocation.flags.ignore_permissions = True
            allocation.insert(ignore_permissions=True)
            allocation.submit()

        credit_entries = frappe.get_all(
            "Leave Ledger Entry",
            filters={
                "transaction_type": "Leave Allocation",
                "transaction_name": allocation.name,
                "employee": employee, "leave_type": LEAVE_TYPE,
                "is_carry_forward": 0, "docstatus": 1,
            },
            fields=["leaves"],
            limit_page_length=0,
        )
        actual_credit = sum(
            (Decimal(str(e.leaves)) for e in credit_entries), Decimal("0")
        )
        expected_cumulative = (
            old_credited + Decimal(plan["hrms_credit"])
            if plan["leave_allocation"] else Decimal(plan["hrms_credit"])
        )
        if abs(actual_credit - expected_cumulative) > Decimal("0.000001"):
            frappe.throw(_("Ledger verification failed; employee posting rolled back"))

        journal.leave_allocation = allocation.name
        journal.status = "Posted"
        journal.posted_on = now_datetime()
        journal.flags.marina_authorized_posting_service = True
        journal.save(ignore_permissions=True)
        return {
            **plan, "journal": journal.name,
            "leave_allocation": allocation.name, "status": "Posted",
            "total_allocation_ledger_credit": str(actual_credit),
        }
    except Exception:
        frappe.db.rollback(save_point="marina_single_employee_post")
        raise
