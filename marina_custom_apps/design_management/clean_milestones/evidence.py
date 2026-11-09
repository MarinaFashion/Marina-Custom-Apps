"""Published Design Document evidence for the clean milestone workflow.

A valid document can be Published independently of a Design Code. On milestone
confirmation, the authorized custodian may explicitly bind the selected
Published document to this Design Code and milestone in the SAME transaction.
An existing per-Design milestone mapping is never silently overwritten.
Required Evidence Type is enforced for every approval path; file access is permission scoped.
"""
import json

import frappe

MAX_CANDIDATES = 500


def matches_milestone(assignment_target, document_target, milestone_type):
    """An assignment override wins; otherwise inherit the document's target."""
    return (assignment_target or document_target) == milestone_type


def matching_published_documents(design_code, milestone_type, evidence_type=None):
    """Bounded, permission-filtered lookup with required evidence-type matching."""
    if not design_code or not milestone_type:
        return []
    links = frappe.get_all(
        "Design Document Assignment",
        filters={
            "parenttype": "Design Document",
            "parentfield": "assignments",
            "design_code": design_code,
        },
        fields=["parent", "target_milestone_type"],
        limit_page_length=MAX_CANDIDATES + 1,
    )
    if len(links) > MAX_CANDIDATES:
        frappe.throw("Too many Design Document assignments to evaluate")
    if not links:
        return []

    names = sorted({link.parent for link in links if link.parent})
    if not names:
        return []

    # Permissions are applied by get_list; get_all could expose private files.
    docs = frappe.get_list(
        "Design Document",
        filters={"name": ["in", names], "publication_status": "Published",
                 "superseded_by": ["is", "not set"],
                 **({"document_type": evidence_type} if evidence_type else {})},
        fields=["name", "document_title", "document_type",
                "related_milestone_type"],
        order_by="modified desc, name desc",
        limit_page_length=len(names),
    )
    targets = {}
    for link in links:
        targets.setdefault(link.parent, []).append(link.target_milestone_type)
    return [
        doc for doc in docs if any(
            matches_milestone(target, doc.related_milestone_type,
                              milestone_type)
            for target in targets.get(doc.name, [])
        )
    ]


def evidence_document_details(design_code, milestone_type, document_name, evidence_type=None):
    """Inspect evidence with document read permission and immutable mappings."""
    doc = frappe.get_doc("Design Document", document_name)
    doc.check_permission("read")
    if doc.publication_status != "Published":
        frappe.throw("Only Published Design Documents can confirm a milestone")
    if evidence_type and doc.document_type != evidence_type:
        frappe.throw(
            "Evidence Type mismatch: " + milestone_type +
            " requires '" + evidence_type + "', but the selected document is '" +
            str(doc.document_type or "") + "'"
        )
    rows = [r for r in doc.get("assignments") or []
            if r.design_code == design_code]
    if len(rows) > 1:
        frappe.throw("Duplicate Design Code assignment in selected document")
    if rows and not matches_milestone(
            rows[0].target_milestone_type, doc.related_milestone_type,
            milestone_type):
        frappe.throw("Document already assigned to this Design under another milestone")
    return doc, bool(rows)


def _bind_to_milestone(doc, design_code, milestone_type, evidence_type):
    """Append one canonical link within authorized workflow transaction.

    Workflow caller locks Design Code first; lock Document next. Retain all
    previous published records and never change the attachment.
    """
    frappe.db.sql(
        "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE", (doc.name,))
    # Another request might have linked the document before this lock.
    doc, linked = evidence_document_details(
        design_code, milestone_type, doc.name, evidence_type)
    if linked:
        return
    if len(doc.get("assignments") or []) >= MAX_CANDIDATES:
        frappe.throw("Too many Design Code assignments")
    from frappe.utils import now_datetime
    from uuid import uuid4
    assignment = frappe.get_doc({
        "doctype": "Design Document Assignment",
        "name": uuid4().hex,
        "parent": doc.name,
        "parenttype": "Design Document",
        "parentfield": "assignments",
        "idx": len(doc.get("assignments") or []) + 1,
        "design_code": design_code,
        "target_milestone_type": milestone_type,
        "mood_board": frappe.db.get_value("Design Code", design_code, "mood_board"),
        "assigned_by": frappe.session.user,
        "assigned_on": now_datetime(),
    })
    assignment.db_insert()
    frappe.db.set_value(
        "Design Document", doc.name, "assignment_count",
        len(doc.get("assignments") or []) + 1)
    doc.add_comment("Info", text=(
        "Linked Published evidence to Design " + design_code +
        " / Milestone " + milestone_type +
        " during milestone approval by " + frappe.session.user))


def required_document(design_code, milestone_type, evidence_type, selected=None,
                      confirm_link=False):
    """Evidence required; unlinked Published documents need explicit consent."""
    if not evidence_type:
        frappe.throw("Step requires an Evidence Type in milestone configuration")
    if selected:
        doc, linked = evidence_document_details(
            design_code, milestone_type, selected, evidence_type)
        if doc.superseded_by:
            frappe.throw("This document was superseded. Select its latest published version")
        if not linked:
            if not confirm_link:
                frappe.throw(
                    "Confirm linking this Published document to Design " +
                    design_code + " / Milestone " + milestone_type)
            _bind_to_milestone(doc, design_code, milestone_type, evidence_type)
        return doc.name
    docs = matching_published_documents(design_code, milestone_type, evidence_type)
    if not docs:
        frappe.throw("Select a Published Design Document to confirm " + milestone_type)
    if len(docs) > 1:
        frappe.throw("Select which Published Design Document confirms this step")
    # Revalidate the chosen document when completing the step.
    evidence_document_details(design_code, milestone_type, docs[0].name, evidence_type)
    return docs[0].name



def check_step_evidence(snapshot, step, design_code, milestone_type, selected=None):
    row = next(
        (r for r in snapshot.get("steps", [])
         if r["step"] == step and r["enabled"]), None,
    )
    if row and row["requires_evidence"]:
        return required_document(design_code, milestone_type,
                                 row["evidence_type"], selected)
    return None


@frappe.whitelist()
def preview_evidence_link(design_code, milestone_type, document_name, step=None):
    """Preview the selected Published document and binding requirement."""
    from marina_custom_apps.design_management.clean_milestones.service import _design
    from marina_custom_apps.design_management.clean_milestones.rules import configured_steps
    _design(design_code)
    plan = frappe.db.get_value(
        "Design Milestone Plan Entry",
        {"design_code": design_code, "milestone_type": milestone_type},
        ["plan_state", "workflow_snapshot_json"], as_dict=True)
    if not plan or plan.plan_state != "Active":
        frappe.throw("The selected milestone is not Active")
    required_types = {
        row["evidence_type"] for row in
        configured_steps(json.loads(plan.workflow_snapshot_json)["steps"])
        if row["requires_evidence"]
    }
    if not required_types:
        frappe.throw("This milestone does not require document evidence")
    if step:
        matches = [
            row for row in configured_steps(json.loads(plan.workflow_snapshot_json)["steps"])
            if row["step"] == step and row["requires_evidence"]
        ]
        if not matches:
            frappe.throw("The selected step does not require evidence")
        required_types = {matches[0]["evidence_type"]}
    doc, linked = evidence_document_details(
        design_code, milestone_type, document_name)
    if doc.superseded_by:
        frappe.throw("This document was superseded. Select its latest published version")
    if doc.document_type not in required_types:
        frappe.throw("Evidence Type does not match the selected milestone workflow")
    return {
        "document": doc.name, "document_title": doc.document_title,
        "document_type": doc.document_type,
        "document_milestone": doc.related_milestone_type,
        "design_code": design_code, "milestone_type": milestone_type,
        "already_linked": linked, "requires_confirmation": not linked,
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_milestone_evidence(doctype, txt, searchfield, start, page_len, filters):
    """Scoped Link picker based only on Design Code and Milestone Type.

    Derive whether evidence is required from the saved Design plan. The
    execution ID is needed only for the final advance_step transaction.
    """
    if doctype != "Design Document":
        return []
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    if not isinstance(filters, dict):
        return []
    code = filters.get("design_code")
    milestone = filters.get("milestone_type")
    step = filters.get("step")
    if not all(
        isinstance(x, str) and 0 < len(x) <= 140
        for x in (code, milestone)
    ):
        return []

    from marina_custom_apps.design_management.clean_milestones.service import _design
    from marina_custom_apps.design_management.clean_milestones.rules import configured_steps

    _design(code)  # Authorize Design Code before searching its documents.
    plan = frappe.db.get_value(
        "Design Milestone Plan Entry",
        {"design_code": code, "milestone_type": milestone},
        ["workflow_snapshot_json", "plan_state"], as_dict=True,
    )
    if not plan or plan.plan_state not in ("Active", "Completed"):
        return []

    snapshot = json.loads(plan.workflow_snapshot_json)
    required_types = {
        row["evidence_type"] for row in configured_steps(snapshot["steps"])
        if row["requires_evidence"]
    }
    if step:
        matches = [
            row for row in configured_steps(snapshot["steps"])
            if row["step"] == step and row["requires_evidence"]
        ]
        if not matches:
            return []
        required_types = {matches[0]["evidence_type"]}
    if not required_types:
        return []

    # The picker may offer an unassigned Published document. Document
    # permissions are scoped by get_list; only one batched child query is used.
    needle = (txt or "").strip()
    if len(needle) > 100:
        return []
    per_page = min(50, max(1, int(page_len)))
    query = {
        "filters": {"publication_status": "Published",
                    "superseded_by": ["is", "not set"],
                    "document_type": ["in", sorted(required_types)]},
        "fields": ["name", "document_title", "related_milestone_type"],
        "order_by": "modified desc, name desc",
        "limit_start": max(0, int(start)),
        "limit_page_length": per_page,
    }
    if needle:
        term = "%" + needle + "%"
        query["or_filters"] = [
            ["Design Document", "name", "like", term],
            ["Design Document", "document_title", "like", term],
        ]
    documents = frappe.get_list("Design Document", **query)
    if not documents:
        return []
    assignments = frappe.get_all(
        "Design Document Assignment",
        filters={
            "parenttype": "Design Document", "parentfield": "assignments",
            "parent": ["in", [doc.name for doc in documents]],
            "design_code": code,
        },
        fields=["parent", "target_milestone_type"],
        limit_page_length=len(documents) + 1,
    )
    by_document = {row.parent: row for row in assignments}
    return [
        (doc.name, doc.document_title or doc.name)
        for doc in documents
        if doc.name not in by_document or matches_milestone(
            by_document[doc.name].target_milestone_type,
            doc.related_milestone_type, milestone)
    ]
