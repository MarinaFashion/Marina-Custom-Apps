"""Public endpoints for the clean milestone engine (no legacy methods)."""
import frappe
from marina_custom_apps.design_management.clean_milestones import service


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
                  designer=None, custody=None, milestone_view="all", factory=None):
    from marina_custom_apps.design_management.clean_milestones.grid import get_grid
    return get_grid(page, page_size, search, mood_board, designer, custody,
                    milestone_view, factory=factory)


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


