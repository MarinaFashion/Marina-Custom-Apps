"""Controlled bulk completion via the existing Release 22 milestone state machine.

No direct status writes, no commits or asynchronous jobs. Each confirmed
transition creates its normal evidence assignment, audit event and follow-up
activities. One failing design rolls the entire request back.
"""
import json

import frappe
from frappe.utils import getdate, now_datetime

from marina_custom_apps.design_management.clean_milestones.rules import configured_steps
from marina_custom_apps.design_management.clean_milestones import service

MAX_BULK = 50


def _selection(items):
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (TypeError, ValueError):
            frappe.throw("Invalid bulk milestone selection")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BULK:
        frappe.throw("Select between 1 and 50 milestones per batch")
    parsed = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"design_code", "execution"}:
            frappe.throw("Invalid bulk milestone row")
        code, name = item["design_code"], item["execution"]
        if any(not isinstance(x, str) or not x or len(x) > 140 for x in (code, name)):
            frappe.throw("Invalid Design Code or execution reference")
        if code in seen:
            frappe.throw("Select only one milestone per Design Code")
        seen.add(code)
        parsed.append((code, name))
    return sorted(parsed)


def _inspect(selected):
    """Recheck source-of-truth records and every actor's individual rights."""
    actor = frappe.session.user
    signature = None
    details = []
    for code, name in selected:
        design = service._design(code)
        row = frappe.db.get_value("Design Milestone Execution", name, "*", as_dict=True)
        if not row or row.design_code != code:
            frappe.throw("Stale bulk selection: execution does not match " + code)
        plan = frappe.db.get_value(
            "Design Milestone Plan Entry", row.plan_entry, "*", as_dict=True)
        if not plan or plan.design_code != code or plan.activated_execution != name:
            frappe.throw("Stale bulk selection: milestone plan differs for " + code)
        if plan.plan_state != "Active" or row.status == "Completed":
            frappe.throw(code + ": milestone is no longer Active")
        if not row.current_custodian:
            frappe.throw(code + ": current custodian is missing")
        current = (row.milestone_type, row.status, row.current_custodian)
        if signature is None:
            signature = current
        elif signature != current:
            frappe.throw(
                "Every selected design must have the same Milestone, Current Step "
                "and Current Custodian")
        snapshot = json.loads(plan.workflow_snapshot_json)
        allowed = {step["step"]: step for step in service._next_allowed(snapshot, row.status)}
        if "Completed" not in allowed:
            frappe.throw(code + ": Completed is not an allowed next step")
        stage = allowed["Completed"]
        service._authorize(actor, "Advance Milestone Step", design,
                           stage["responsible_module_role"],
                           custodian=row.current_custodian)
        # Verify that a valid target owner can be assigned before any writes.
        service._role_user(design, stage["custody_role"])
        details.append({
            "design_code": code,
            "execution": name,
            "milestone_type": row.milestone_type,
            "step": row.status,
            "custodian": row.current_custodian,
            "evidence_type": stage["evidence_type"] if stage["requires_evidence"] else None,
            "step_entered_on": row.step_entered_on,
        })
    required_types = {item["evidence_type"] for item in details}
    if len(required_types) != 1:
        frappe.throw("The selected milestones must have the same evidence requirement")
    return details


@frappe.whitelist()
def preview_bulk_completion(selected):
    rows = _inspect(_selection(selected))
    head = rows[0]
    return {
        "count": len(rows),
        "milestone_type": head["milestone_type"],
        "current_step": head["step"],
        "custodian": head["custodian"],
        "evidence_type": head["evidence_type"],
        "design_codes": [row["design_code"] for row in rows],
        "earliest_completion_date": max(
            str(getdate(row["step_entered_on"])) for row in rows
        ),
    }


@frappe.whitelist(methods=["POST"])
def complete_bulk(selected, evidence_document=None, step_change_date=None,
                  reason=None, confirm_evidence_link=False):
    parsed = _selection(selected)
    if not isinstance(step_change_date, str) or not step_change_date:
        frappe.throw("Select the completion date")
    if getdate(step_change_date) > getdate(now_datetime()):
        frappe.throw("Completion date cannot be in the future")
    # Acquire all Design Code locks in stable order before touching evidence
    # or beginning the existing advance() business transaction.
    for code, _ in parsed:
        service._lock_design(code)
    rows = _inspect(parsed)
    required = rows[0]["evidence_type"]
    if required and not evidence_document:
        frappe.throw("Select one Published Evidence document for all designs")
    if not required and evidence_document:
        frappe.throw("This milestone step does not require evidence")
    if required:
        from marina_custom_apps.design_management.clean_milestones.evidence import (
            evidence_document_details,
        )
        for row in rows:
            doc, linked = evidence_document_details(
                row["design_code"], row["milestone_type"],
                evidence_document, required)
            if doc.superseded_by:
                frappe.throw("Evidence document was superseded")
            if not linked and str(confirm_evidence_link).lower() not in ("1", "true"):
                frappe.throw("Confirm sharing this Published document across selected designs")
    # Single HTTP transaction. A failure propagates, and Frappe rolls
    # back all earlier advances plus evidence assignments and events.
    results = []
    for row in rows:
        service.advance(
            row["design_code"], row["execution"], "Completed",
            reason=reason, evidence_document=evidence_document,
            confirm_evidence_link=bool(required),
            step_change_date=step_change_date,
        )
        results.append(row["design_code"])
    return {"completed": len(results), "design_codes": results,
            "milestone_type": rows[0]["milestone_type"]}
