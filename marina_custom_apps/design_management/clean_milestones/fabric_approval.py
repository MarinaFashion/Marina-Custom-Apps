"""Conditional Fabric / Material Sourcing workflow for a Design Code.

The standard two-step milestone master remains unchanged. A per-design
snapshot decides whether Designer review, rejection and resubmission apply.
"""
import json

import frappe

from marina_custom_apps.design_management.clean_milestones.rules import configured_steps

MILESTONE = "Fabric / Material Sourcing"
VALUES = ("Required", "Not Required")


def approval_steps(base_steps, approval):
    """Derive both paths from the frozen original sourcing role and lead time."""
    if approval not in VALUES:
        frappe.throw("Select Fabric Approval before creating milestones")
    rows = configured_steps(base_steps)
    sourcing = next((x for x in rows if x["step"] == "In Progress"), None)
    completed = next((x for x in rows if x["step"] == "Completed"), None)
    if not sourcing or not completed:
        frappe.throw("Fabric Sourcing master must contain In Progress and Completed")
    role = sourcing["custody_role"]
    if not role or sourcing["transition_mode"] != "Auto":
        frappe.throw("Fabric Sourcing must start automatically with an assigned sourcing role")

    def step(name, mode, actor, custody, lead=0, evidence=False, evidence_type=None):
        return {
            "step": name, "enabled": True, "transition_mode": mode,
            "responsible_module_role": actor, "custody_role": custody,
            "lead_time_days": lead, "requires_evidence": bool(evidence),
            "evidence_type": evidence_type if evidence else None,
        }

    first = step("In Progress", "Auto", None, role,
                 sourcing["lead_time_days"])
    last = step("Completed", "Manual",
                "Designer" if approval == "Required" else role,
                "Designer" if approval == "Required" else role,
                completed["lead_time_days"], completed["requires_evidence"],
                completed["evidence_type"])
    if approval == "Not Required":
        result = [first, last]
    else:
        result = [
            first, step("Ready", "Manual", role, "Designer"),
            step("Rework", "Manual", "Designer", role),
            last,
        ]
    configured_steps(result)
    return result


def configure_snapshot(snapshot, approval):
    if snapshot["name"] != MILESTONE:
        return snapshot
    # Retain the immutable original configuration for later controlled changes.
    base = snapshot.get("fabric_base_steps") or snapshot["steps"]
    snapshot["fabric_base_steps"] = base
    snapshot["fabric_approval"] = approval
    snapshot["steps"] = approval_steps(base, approval)
    return snapshot


def switch_existing_plan(design, approval, reason):
    """Called only with the Design Code row locked inside the same transaction."""
    from marina_custom_apps.design_management.clean_milestones import service

    plans = frappe.db.sql("""
        SELECT name, plan_state, activated_execution, workflow_snapshot_json
        FROM `tabDesign Milestone Plan Entry`
        WHERE design_code=%s AND milestone_type=%s FOR UPDATE
    """, (design.name, MILESTONE), as_dict=True)
    if len(plans) != 1:
        frappe.throw("Exactly one Fabric Sourcing milestone plan is required")
    plan = plans[0]
    if plan.plan_state == "Completed":
        frappe.throw("Fabric Approval cannot change after Fabric Sourcing is completed")
    if plan.plan_state not in ("Planned", "Active"):
        frappe.throw("Fabric Sourcing plan has an unsupported state")
    cfg = json.loads(plan.workflow_snapshot_json)
    configure_snapshot(cfg, approval)
    # Check assignments before changing the workflow or custody.
    sourcing_role = next(x["custody_role"] for x in cfg["steps"]
                         if x["step"] == "In Progress")
    sourcing_user = service._role_user(design, sourcing_role)
    if approval == "Required":
        service._role_user(design, "Designer")
    if plan.plan_state == "Active":
        if not plan.activated_execution:
            frappe.throw("Active Fabric Sourcing plan has no execution")
        execution = frappe.db.get_value(
            "Design Milestone Execution", plan.activated_execution, "*", as_dict=True)
        if not execution or execution.plan_entry != plan.name:
            frappe.throw("Fabric Sourcing execution does not match plan")
        if execution.status == "Completed":
            frappe.throw("Completed Fabric Sourcing cannot be changed")
        previous = execution.status
        prior_user = execution.current_custodian
        # An outstanding review is withdrawn rather than treated as approval.
        # Submitted evidence stays referenced in the audit history.
        if previous in ("Ready", "Rework") or prior_user != sourcing_user:
            from frappe.utils import now_datetime
            entered = now_datetime()
            frappe.db.set_value("Design Milestone Execution", execution.name, {
                "status": "In Progress",
                "current_role": sourcing_role,
                "current_custodian": sourcing_user,
                "step_entered_on": entered,
                "last_action_on": entered,
                "due_date": service._target_date(entered, cfg, "In Progress"),
                "latest_note": reason,
            }, update_modified=False)
            service._event(
                design, plan, frappe._dict(name=execution.name, status="In Progress",
                                           current_custodian=sourcing_user),
                "Fabric Approval Changed", old=previous, prior=prior_user,
                reason=reason, actor=frappe.session.user,
                evidence=execution.evidence_document,
                evidence_file=execution.evidence_file,
            )
        else:
            service._event(
                design, plan, execution, "Fabric Approval Changed",
                old=previous, prior=prior_user, reason=reason,
                actor=frappe.session.user,
                evidence=execution.evidence_document,
                evidence_file=execution.evidence_file,
            )
    frappe.db.set_value("Design Milestone Plan Entry", plan.name,
                        "workflow_snapshot_json",
                        json.dumps(cfg, sort_keys=True, default=str),
                        update_modified=False)
    return plan.plan_state
