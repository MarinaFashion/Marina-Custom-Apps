"""Controlled return to a previously reached milestone (Release 22).

This is NOT deletion. Plans, execution identities and custody events survive.
One Design Code row lock serializes rollback with normal workflow transitions.
All changes occur in Frappe's request transaction; never commit here.
"""
import hashlib
import json

import frappe
from frappe.utils import now_datetime

from marina_custom_apps.design_management.clean_milestones.rules import configured_steps
from marina_custom_apps.design_management.clean_milestones.return_rules import later_plans
from marina_custom_apps.design_management.security.role_access import can_action

MAX_PLANS = 50


def _authorized(design):
    if not (can_action("Return to Milestone", frappe.session.user)
            and frappe.has_permission("Design Code", "write",
                                      doc=design, user=frappe.session.user)):
        frappe.throw("Return to Milestone permission required", frappe.PermissionError)


def _state(design_code):
    plans = frappe.get_all(
        "Design Milestone Plan Entry",
        filters={"design_code": design_code},
        fields=["name", "design_code", "milestone_type", "sequence",
                "plan_state", "depends_on_type", "activated_execution",
                "workflow_snapshot_json"],
        order_by="sequence asc, milestone_type asc",
        limit_page_length=MAX_PLANS + 1,
    )
    if len(plans) > MAX_PLANS:
        frappe.throw("Too many milestone plans for a safe return")
    executions = frappe.get_all(
        "Design Milestone Execution",
        filters={"design_code": design_code},
        fields=["name", "plan_entry", "design_code", "status", "current_role",
                "current_custodian", "evidence_document", "evidence_file", "last_action_on"],
        limit_page_length=MAX_PLANS + 1,
    )
    if len(executions) > MAX_PLANS:
        frappe.throw("Too many executions for a safe milestone return")
    by_plan = {e.plan_entry: e for e in executions}
    if len(by_plan) != len(executions):
        frappe.throw("Duplicate milestone executions must be resolved first")
    return plans, by_plan


def _return_steps(plan):
    cfg = json.loads(plan.workflow_snapshot_json)
    return cfg, [r for r in configured_steps(cfg["steps"])
                 if r["step"] != "Completed"]


def _revision(plans, executions, target_name, step):
    rows = [
        (p.name, p.milestone_type, p.sequence, p.plan_state,
         p.activated_execution,
         executions[p.name].status if p.name in executions else None,
         str(executions[p.name].last_action_on)
         if p.name in executions else None)
        for p in plans
    ]
    return hashlib.sha256(json.dumps(
        [target_name, step, rows], ensure_ascii=False,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _prepare(design, target_name, step, plans, executions):
    from marina_custom_apps.design_management.clean_milestones.service import _role_user
    target = next((p for p in plans if p.milestone_type == target_name), None)
    if not target or target.plan_state not in ("Active", "Completed"):
        frappe.throw("Select a milestone that has already been activated")
    current = executions.get(target.name)
    if not current or current.name != target.activated_execution:
        frappe.throw("Target milestone has no valid active execution")
    cfg, steps = _return_steps(target)
    selected = next((row for row in steps if row["step"] == step), None)
    if not selected:
        frappe.throw("Select an enabled step before Completed from the saved milestone workflow")
    names = [r["step"] for r in steps if r["step"] != "Rework"]
    if current.status in names and step in names and names.index(step) > names.index(current.status):
        frappe.throw("Return cannot move a milestone forward; use normal step actions")
    custodian = _role_user(design, selected["custody_role"])
    later = later_plans(plans, target)
    if target.depends_on_type in {p.milestone_type for p in later}:
        frappe.throw("Milestone display order conflicts with dependencies; correct the plan first")
    changed = [p for p in later if p.plan_state != "Planned"]
    for plan in changed:
        execution = executions.get(plan.name)
        if not execution or plan.activated_execution != execution.name:
            frappe.throw("Downstream milestone has an invalid execution; return was cancelled")
    if (current.status == step and current.current_custodian == custodian
            and target.plan_state == "Active" and not changed):
        frappe.throw("The milestone already has this step and custody; nothing to return")
    return target, current, cfg, selected, custodian, changed


@frappe.whitelist()
def can_open_return_action(design_code):
    """Menu capability independent of milestone activation state.

    Authorized users may open the return dialog before a plan is created; the
    existing return_options and execute_return endpoints independently deny
    invalid transitions. No write permissions are granted by this helper.
    """
    from marina_custom_apps.design_management.clean_milestones.service import _design
    design = _design(design_code)
    return bool(
        can_action("Return to Milestone")
        and frappe.has_permission("Design Code", "write", doc=design)
    )


@frappe.whitelist()
def can_return_to_milestone(design_code):
    from marina_custom_apps.design_management.clean_milestones.service import _design
    design = _design(design_code)
    if not (can_action("Return to Milestone")
            and frappe.has_permission("Design Code", "write", doc=design)):
        return False
    return bool(frappe.db.exists(
        "Design Milestone Plan Entry",
        {"design_code": design_code, "plan_state": ["in", ["Active", "Completed"]]}))


@frappe.whitelist()
def return_options(design_code):
    from marina_custom_apps.design_management.clean_milestones.service import _design
    design = _design(design_code)
    _authorized(design)
    plans, executions = _state(design_code)
    result = []
    for plan in plans:
        if plan.plan_state not in ("Active", "Completed"):
            continue
        exe = executions.get(plan.name)
        if not exe or exe.name != plan.activated_execution:
            continue
        _, steps = _return_steps(plan)
        result.append({
            "milestone_type": plan.milestone_type,
            "current_step": exe.status,
            "steps": [{"step": r["step"], "custody_role": r["custody_role"]}
                      for r in steps],
        })
    return result


@frappe.whitelist()
def preview_return(design_code, milestone_type, step):
    from marina_custom_apps.design_management.clean_milestones.service import _design
    design = _design(design_code)
    _authorized(design)
    plans, executions = _state(design_code)
    target, current, cfg, selected, custodian, changed = _prepare(
        design, milestone_type, step, plans, executions)
    return {
        "design_code": design_code,
        "milestone_type": target.milestone_type,
        "from_step": current.status,
        "to_step": step,
        "custody_role": selected["custody_role"],
        "custodian": custodian,
        "custodian_title": frappe.db.get_value("User", custodian, "username") or "",
        "to_future": [
            {"milestone_type": p.milestone_type, "was": p.plan_state,
             "step": executions[p.name].status}
            for p in changed
        ],
        "revision": _revision(plans, executions, milestone_type, step),
    }


@frappe.whitelist(methods=["POST"])
def execute_return(design_code, milestone_type, step, reason, expected_revision):
    from marina_custom_apps.design_management.clean_milestones.service import (
        _design, _event, _lock_design, _target_date,
    )
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 500:
        frappe.throw("Provide a return reason (10–500 characters)")
    if not isinstance(expected_revision, str) or len(expected_revision) != 64:
        frappe.throw("Preview the return before confirming")
    _lock_design(design_code)
    design = _design(design_code)
    _authorized(design)
    plans, executions = _state(design_code)
    target, current, cfg, selected, custodian, changed = _prepare(
        design, milestone_type, step, plans, executions)
    if _revision(plans, executions, milestone_type, step) != expected_revision:
        frappe.throw("Milestones changed since preview. Refresh and review the impact again.")
    moment = now_datetime()

    # All subsequent executed plans return to Future. Keep their execution
    # records to preserve immutable custody-event Link references. Clear the
    # operational state and allow _activate to reuse the identity on restart.
    for plan in changed:
        exe = executions[plan.name]
        old_step, old_custodian, old_evidence, old_file = (
            exe.status, exe.current_custodian, exe.evidence_document, exe.evidence_file)
        downstream_cfg = json.loads(plan.workflow_snapshot_json)
        initial = configured_steps(downstream_cfg["steps"])[0]
        frappe.db.set_value("Design Milestone Plan Entry", plan.name,
                            "plan_state", "Planned", update_modified=False)
        frappe.db.set_value("Design Milestone Execution", exe.name, {
            "status": initial["step"], "current_role": None,
            "current_custodian": None, "step_entered_on": None,
            "due_date": None, "completed_by": None, "completed_on": None,
            "evidence_document": None, "evidence_file": None, "latest_note": None,
            "rework_count": 0, "last_action_on": moment,
        }, update_modified=False)
        # Planned is a PLAN state, not an Execution step; use it solely in
        # the event to make the return explicit and preserve the old evidence.
        planned_event = frappe._dict(
            name=exe.name, status="Planned", current_custodian=None)
        _event(design, plan, planned_event, "Returned to Future",
               old=old_step, prior=old_custodian, reason=reason,
               evidence=old_evidence, evidence_file=old_file)

    old_step, old_custodian, old_evidence, old_file = (
        current.status, current.current_custodian, current.evidence_document,
        current.evidence_file)
    frappe.db.set_value("Design Milestone Execution", current.name, {
        "status": step, "current_role": selected["custody_role"],
        "current_custodian": custodian, "step_entered_on": moment,
        "due_date": _target_date(moment, cfg, step),
        "completed_by": None, "completed_on": None,
        "evidence_document": None, "evidence_file": None, "latest_note": reason,
        "last_action_on": moment, "rework_count": 0,
    }, update_modified=False)
    frappe.db.set_value("Design Milestone Plan Entry", target.name,
                        "plan_state", "Active", update_modified=False)
    returned = frappe._dict(
        name=current.name, status=step, current_custodian=custodian)
    _event(design, target, returned, "Returned to Milestone",
           old=old_step, prior=old_custodian,
           reason=reason, evidence=old_evidence,
            evidence_file=old_file)
    return {
        "returned": target.milestone_type, "status": step,
        "custodian": custodian, "moved_to_future": len(changed),
    }
