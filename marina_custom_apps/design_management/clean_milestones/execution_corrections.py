"""Audited administrative correction of execution dates.

Never edit workflow status, plan state, custody, or evidence here. Those
properties are owned by the controlled milestone transition engine.
"""
import frappe
from frappe.utils import get_datetime, getdate, now_datetime

from marina_custom_apps.design_management.clean_milestones.service import (
    _design, _event, _is_admin, _lock_design,
)


@frappe.whitelist(methods=["POST"])
def correct_execution_dates(execution_name, target_date, completed_on, reason,
                            expected_last_action_on):
    actor = frappe.session.user
    if not _is_admin(actor):
        frappe.throw("Administrator or System Manager required", frappe.PermissionError)
    if not isinstance(execution_name, str) or not 0 < len(execution_name) <= 140:
        frappe.throw("Select an existing execution")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(reason) <= 500:
        frappe.throw("Enter a correction reason (10–500 characters)")
    if not isinstance(expected_last_action_on, str):
        frappe.throw("Refresh the execution before making a correction")

    # Look up the parent before locking; recheck the relationship under lock.
    design_code = frappe.db.get_value(
        "Design Milestone Execution", execution_name, "design_code")
    if not design_code:
        frappe.throw("Execution not found")
    _lock_design(design_code)
    design = _design(design_code)
    row = frappe.db.get_value("Design Milestone Execution", execution_name,
        ["name", "design_code", "plan_entry", "milestone_type", "status",
         "current_custodian", "due_date", "completed_on",
         "step_entered_on", "last_action_on"], as_dict=True)
    if not row or row.design_code != design.name:
        frappe.throw("Execution changed; refresh and retry")
    plan = frappe.db.get_value("Design Milestone Plan Entry", row.plan_entry,
        ["name", "design_code", "milestone_type", "plan_state",
         "activated_execution"], as_dict=True)
    if (not plan or plan.design_code != design.name
            or plan.milestone_type != row.milestone_type
            or plan.activated_execution != row.name
            or plan.plan_state not in ("Active", "Completed")):
        frappe.throw("Execution is not the active record of a valid milestone plan")
    if str(row.last_action_on or "") != expected_last_action_on:
        frappe.throw("Execution changed since opening this form. Refresh and retry.")

    if not isinstance(target_date, str) or len(target_date) != 10:
        frappe.throw("Provide Target Date as YYYY-MM-DD")
    try:
        corrected_due = getdate(target_date)
        if corrected_due.isoformat() != target_date:
            raise ValueError("Invalid date")
    except (TypeError, ValueError):
        frappe.throw("Invalid Target Date")
    if row.status == "Completed":
        if plan.plan_state != "Completed":
            frappe.throw("Completed execution has inconsistent plan state")
        if not isinstance(completed_on, str) or not completed_on.strip():
            frappe.throw("Completed On is required for a completed milestone")
        try:
            corrected_completed = get_datetime(completed_on)
        except (TypeError, ValueError):
            frappe.throw("Invalid Completed On datetime")
        if corrected_completed > now_datetime():
            frappe.throw("Completion cannot be dated in the future")
        if getdate(corrected_completed) < getdate(design.creation_date or design.creation):
            frappe.throw("Completion cannot precede Design creation")
    else:
        if completed_on:
            frappe.throw("Only Completed milestones may have a completion timestamp")
        corrected_completed = None

    updates = {}
    if corrected_due != getdate(row.due_date) if row.due_date else True:
        updates["due_date"] = corrected_due
    if row.status == "Completed" and corrected_completed != get_datetime(row.completed_on):
        # For a completed execution, step_entered_on is also the effective
        # completion-step timestamp; keep the two aligned.
        updates["completed_on"] = corrected_completed
        updates["step_entered_on"] = corrected_completed
    if not updates:
        frappe.throw("No date changes were provided")

    before = ", ".join(
        key + ": " + str(row.get(key) or "—") + " -> " + str(updates[key])
        for key in updates
    )
    moment = now_datetime()
    updates["last_action_on"] = moment
    frappe.db.set_value("Design Milestone Execution", row.name,
                        updates, update_modified=False)
    _event(design, plan, row, "Execution Dates Corrected",
        old=row.status, prior=row.current_custodian,
        reason=reason + " | " + before,
        effective_date=corrected_completed or corrected_due)
    return {"execution": row.name, "corrected": list(updates),
            "audit": "Design Milestone Custody Event"}
