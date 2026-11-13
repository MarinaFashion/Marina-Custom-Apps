"""Safe, permission-checked batch changes to Design Code Fabric Approval.

The transaction covers all selected designs (max 20) and commits only when
every selected Design Code remains eligible. No direct bypass of active plans.
"""
import frappe

from marina_custom_apps.design_management.clean_milestones import service
from marina_custom_apps.design_management.clean_milestones.fabric_approval import (
    MILESTONE, VALUES, switch_existing_plan,
)

MAX_BATCH = 20


def _names(design_codes):
    if isinstance(design_codes, str):
        design_codes = frappe.parse_json(design_codes)
    if not isinstance(design_codes, list) or not 1 <= len(design_codes) <= MAX_BATCH:
        frappe.throw("Select between 1 and 20 Design Codes")
    if any(not isinstance(name, str) or not name or len(name) > 140
           for name in design_codes) or len(set(design_codes)) != len(design_codes):
        frappe.throw("Invalid or duplicate Design Codes")
    # Stable locking order across simultaneous bulk requests.
    return sorted(design_codes)


def _inspect_one(name, approval):
    design = service._design(name)
    design.check_permission("write")
    service._authorize(frappe.session.user, "Assign Milestones", design)
    previous = design.get("fabric_approval_required") or ""
    plans = frappe.get_all(
        "Design Milestone Plan Entry",
        filters={"design_code": name},
        fields=["name", "milestone_type", "plan_state"],
        limit_page_length=service.MAX_SELECTED + 1,
    )
    reasons = []
    if len(plans) > service.MAX_SELECTED:
        reasons.append("Too many milestone plan records")
    fabric = [p for p in plans if p.milestone_type == MILESTONE]
    if plans and len(fabric) != 1:
        reasons.append("No unique Fabric / Material Sourcing milestone in existing plan")
    if fabric and fabric[0].plan_state not in ("Planned", "Active"):
        reasons.append("Fabric Sourcing is completed or unavailable")
    status = "unchanged" if previous == approval else ("blocked" if reasons else "ready")
    return {"design_code": name, "previous": previous or "Not Set",
            "status": status, "reasons": reasons,
            "has_plan": bool(plans)}


@frappe.whitelist()
def preview_bulk_fabric_approval(design_codes, approval):
    if approval not in VALUES:
        frappe.throw("Select Required or Not Required")
    rows = [_inspect_one(name, approval) for name in _names(design_codes)]
    return {"designs": rows, "selected": len(rows),
            "ready": sum(x["status"] == "ready" for x in rows),
            "unchanged": sum(x["status"] == "unchanged" for x in rows),
            "blocked": sum(x["status"] == "blocked" for x in rows)}


@frappe.whitelist(methods=["POST"])
def set_bulk_fabric_approval(design_codes, approval, reason, confirm=0):
    if approval not in VALUES:
        frappe.throw("Select Required or Not Required")
    if not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 350:
        frappe.throw("Provide a reason of 5–350 characters")
    if str(confirm).lower() not in ("1", "true"):
        frappe.throw("Confirm the bulk Fabric Approval update")
    names = _names(design_codes)
    # Acquire the same design lock as individual milestone actions.
    for name in names:
        service._lock_design(name)
    rows = [_inspect_one(name, approval) for name in names]
    if any(row["status"] == "blocked" for row in rows):
        frappe.throw("At least one selected Design Code is ineligible. Refresh the preview; no changes were applied.")
    changed = 0
    for row in rows:
        if row["status"] == "unchanged":
            continue
        name = row["design_code"]
        design = service._design(name)
        previous = design.get("fabric_approval_required") or ""
        note = "Fabric Approval: {} → {}. Reason: {}".format(
            previous or "Not Set", approval, reason.strip())
        if row["has_plan"]:
            switch_existing_plan(design, approval, note)
        frappe.db.set_value("Design Code", name, "fabric_approval_required",
                            approval, update_modified=False)
        frappe.get_doc({
            "doctype": "Comment", "comment_type": "Info",
            "reference_doctype": "Design Code", "reference_name": name,
            "content": note,
        }).insert(ignore_permissions=True)
        changed += 1
    return {"updated": changed, "unchanged": len(rows) - changed}
