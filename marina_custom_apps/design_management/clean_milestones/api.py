"""Public endpoints for the clean milestone engine (no legacy methods)."""
import frappe
from marina_custom_apps.design_management.clean_milestones import service


@frappe.whitelist()
def fabric_approval_change_info(design_code):
    from marina_custom_apps.design_management.clean_milestones import service
    from marina_custom_apps.design_management.clean_milestones.fabric_approval import MILESTONE
    design = service._design(design_code)
    from marina_custom_apps.design_management.security.role_access import can_action
    can_edit = frappe.has_permission("Design Code", "write", doc=design)
    plans = frappe.get_all(
        "Design Milestone Plan Entry",
        filters={"design_code": design.name, "milestone_type": MILESTONE},
        fields=["plan_state"], limit_page_length=2,
    )
    has_plan = bool(frappe.db.exists(
        "Design Milestone Plan Entry", {"design_code": design.name}))
    return {
        "has_plan": has_plan,
        "can_set_initial": bool(can_edit and can_action(
            "Set Initial Fabric Approval", frappe.session.user)),
        "can_change": bool(
            can_edit and can_action("Change Fabric Approval", frappe.session.user)
            and has_plan and len(plans) == 1
            and plans[0].plan_state in ("Planned", "Active")),
        "can_change_before_plan": bool(can_edit and can_action(
            "Change Fabric Approval", frappe.session.user)),
    }


@frappe.whitelist(methods=["POST"])
def change_fabric_approval(design_code, approval, reason, previous_approval=None):
    """Authorized, audited change while Fabric Sourcing is not completed."""
    from marina_custom_apps.design_management.clean_milestones import service
    from marina_custom_apps.design_management.clean_milestones.fabric_approval import (
        VALUES, switch_existing_plan,
    )
    if approval not in VALUES or previous_approval not in (*VALUES, "", None):
        frappe.throw("Select a valid Fabric Approval value")
    if not isinstance(reason, str) or len(reason.strip()) < 5 or len(reason) > 500:
        frappe.throw("Enter a change reason between 5 and 500 characters")
    service._lock_design(design_code)
    design = service._design(design_code)
    design.check_permission("write")
    service._authorize(frappe.session.user, "Change Fabric Approval", design)
    saved = frappe.db.get_value("Design Code", design_code, "fabric_approval_required")
    # Legacy records have NULL/blank approval; JavaScript may omit undefined
    # arguments from frappe.call. Normalize both sides without losing the
    # optimistic-concurrency check for already classified designs.
    if (saved or "") != (previous_approval or ""):
        frappe.throw("Fabric Approval changed. Refresh this Design before retrying")
    if approval == saved:
        return {"unchanged": True, "fabric_approval": saved}
    old = saved
    audit_note = "Fabric Approval: {} → {}. Reason: {}".format(
        old or "Not Set", approval, reason.strip())
    state = switch_existing_plan(design, approval, audit_note)
    frappe.db.set_value("Design Code", design_code, "fabric_approval_required",
                        approval, update_modified=False)
    # Preserve a traceable timeline entry even for Planned milestones with
    # no execution/custody event yet. Roll back with the same transaction.
    frappe.get_doc({
        "doctype": "Comment", "comment_type": "Info",
        "reference_doctype": "Design Code", "reference_name": design_code,
        "content": audit_note,
    }).insert(ignore_permissions=True)
    return {"fabric_approval": approval, "previous": old,
            "plan_state": state}


@frappe.whitelist()
def available_milestones(design_code):
    service._design(design_code)
    rows = frappe.get_all("Design Milestone Type",
        filters={"is_active": 1},
        fields=["name", "sequence", "start_with_design_creation",
                "depends_on_type", "r22_trigger_status"],
        order_by="sequence asc, name asc", limit_page_length=100)
    if not rows:
        return rows
    child_rows = frappe.get_all("Design Milestone Step Template",
        filters={"parenttype": "Design Milestone Type",
                 "parentfield": "workflow_steps",
                 "parent": ["in", [r.name for r in rows]]},
        fields=["parent", "idx", "step", "enabled", "lead_time_days"],
        order_by="parent asc, idx asc", limit_page_length=len(rows)*8+1)
    if len(child_rows) > len(rows)*8:
        frappe.throw("Too many workflow steps in milestone masters")
    steps_by_master = {r.name: [] for r in rows}
    for step in child_rows:
        if step.enabled and step.step != "Rework":
            steps_by_master[step.parent].append({
                "step": step.step, "lead_time_days": int(step.lead_time_days or 0)
            })
    design = service._design(design_code)
    baseline = str(design.creation_date or design.creation)[:10]
    for row in rows:
        row["workflow_steps"] = steps_by_master[row.name]
        row["design_creation_date"] = baseline
        row["default_lead_days"] = sum(
            s["lead_time_days"] for s in steps_by_master[row.name][1:])
    return rows


@frappe.whitelist(methods=["POST"])
def create_plan(design_code, milestone_types, lead_time_overrides=None):
    return service.create_plan(design_code, milestone_types, lead_time_overrides)


@frappe.whitelist(methods=["POST"])
def advance_step(design_code, execution_name, next_step,
                 reason=None, evidence_document=None,
                 confirm_evidence_link=False, step_change_date=None):
    return service.advance(design_code, execution_name, next_step,
                           reason, evidence_document, confirm_evidence_link,
                           step_change_date)


@frappe.whitelist()
def overview(design_code):
    return service.overview(design_code)


@frappe.whitelist()
def history(design_code, offset=0, limit=50):
    return service.history(design_code, offset, limit)


# Unified grid uses the same permission-checked overview/history/advance endpoints.
@frappe.whitelist()
def followup_grid(page=1, page_size=50, search=None, mood_board=None,
                  designer=None, custody=None, milestone_view="all", factory=None,
                  design_codes=None, dashboard_milestone=None,
                  year=None, season=None, collection=None, drop=None,
                  assigned_merchandiser=None, deadline_status=None,
                  current_milestone=None, milestone_type=None):
    from marina_custom_apps.design_management.clean_milestones.grid import get_grid
    return get_grid(
        page, page_size, search, mood_board, designer, custody,
        milestone_view, factory=factory, design_codes=design_codes,
        dashboard_milestone=dashboard_milestone, year=year, season=season,
        collection=collection, drop=drop,
        assigned_merchandiser=assigned_merchandiser,
        deadline_status=deadline_status,
        current_milestone=current_milestone, milestone_type=milestone_type,
    )


@frappe.whitelist()
def followup_milestone_types():
    """All configured milestone types for the shared Follow-Up Grid picker."""
    if not frappe.has_permission("Design Code", "read"):
        frappe.throw("Design Code read permission required", frappe.PermissionError)
    rows = frappe.get_all(
        "Design Milestone Type",
        fields=["name"],
        order_by="sequence asc, name asc",
        limit_page_length=101,
    )
    if len(rows) > 100:
        frappe.throw("Too many configured Milestone Types")
    return [row.name for row in rows]


@frappe.whitelist()
def has_my_current_custody():
    from marina_custom_apps.design_management.clean_milestones.grid import (
        has_my_current_custody as check_custody,
    )
    return check_custody()


@frappe.whitelist(methods=["POST"])
def save_followup_notes(changes):
    from marina_custom_apps.design_management.clean_milestones.grid import save_grid_notes
    return save_grid_notes(changes)




@frappe.whitelist()
def preview_bulk_completion(selected, reason=None):
    from marina_custom_apps.design_management.clean_milestones.bulk_completion import (
        preview_bulk_completion as preview,
    )
    return preview(selected, reason=reason)


@frappe.whitelist(methods=["POST"])
def complete_bulk_milestones(selected, evidence_document=None,
                             step_change_date=None, reason=None,
                             confirm_evidence_link=False):
    from marina_custom_apps.design_management.clean_milestones.bulk_completion import (
        complete_bulk,
    )
    return complete_bulk(selected, evidence_document, step_change_date,
                         reason, confirm_evidence_link)
