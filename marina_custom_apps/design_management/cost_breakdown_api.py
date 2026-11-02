"""Authorized workflow actions for Marina Design Cost Breakdown v1."""
import frappe
from frappe.utils import now_datetime, nowdate

from marina_custom_apps.marina_design_management.doctype.design_cost_breakdown.design_cost_breakdown import (
    _allowed_design, _buyer, _preparer,
)


def _design_and_doc(name):
    doc = frappe.get_doc("Design Cost Breakdown", name)
    design = frappe.get_doc("Design Code", doc.design_code)
    if not _allowed_design(design):
        frappe.throw("No permission for this design.", frappe.PermissionError)
    return design, doc


def _prepare_access(design, doc=None, create=False):
    if not _preparer(design):
        frappe.throw("Only the assigned Merchandiser or Head of Merchandisers may manage drafts.",
                     frappe.PermissionError)
    # Direct whitelisted methods must not bypass Marina DocType RBAC, even
    # though the actual write is made by a server-authorized workflow action.
    from marina_custom_apps.design_management.security.role_access import can_doctype
    permission = "create" if create else "write"
    if can_doctype("Design Cost Breakdown", permission) is False:
        frappe.throw("Module role does not permit this Cost Breakdown action.",
                     frappe.PermissionError)
    if not create and doc is not None and not frappe.has_permission(
            "Design Cost Breakdown", "write", doc=doc):
        frappe.throw("Write permission required for this Draft.", frappe.PermissionError)
    if create and not frappe.has_permission("Design Cost Breakdown", "create"):
        frappe.throw("Create permission required for a new Cost Breakdown.", frappe.PermissionError)


def _approval_access(design, doc):
    if not _buyer():
        frappe.throw("Only the authorized Buying Manager may review cost quotations.",
                     frappe.PermissionError)
    user = frappe.session.user
    if user not in ("Administrator",) and user in (doc.prepared_by, doc.submitted_by):
        frappe.throw("The preparer cannot approve or return their own quotation.",
                     frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def submit_cost_breakdown(name):
    design, doc = _design_and_doc(name)
    _prepare_access(design, doc=doc)
    if doc.status not in ("Draft", "Returned"):
        frappe.throw("Only Draft or Returned Cost Breakdowns can be submitted.")
    frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                  (doc.design_code,))
    doc.status = "Pending Approval"
    doc.submitted_by = frappe.session.user
    doc.submitted_on = now_datetime()
    doc.returned_by = None
    doc.returned_on = None
    doc.return_reason = None
    doc.flags.cost_transition = "submit"
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def return_cost_breakdown(name, reason):
    design, doc = _design_and_doc(name)
    _approval_access(design, doc)
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 500:
        frappe.throw("Provide a return reason between 10 and 500 characters.")
    frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                  (doc.design_code,))
    doc.reload()
    if doc.status != "Pending Approval":
        frappe.throw("Only Pending Approval Cost Breakdowns can be returned.")
    doc.status = "Returned"
    doc.returned_by = frappe.session.user
    doc.returned_on = now_datetime()
    doc.return_reason = reason
    doc.flags.cost_transition = "return"
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def approve_cost_breakdown(name):
    design, doc = _design_and_doc(name)
    _approval_access(design, doc)
    # Serializes concurrent approvals for the same design.
    frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                  (doc.design_code,))
    doc.reload()
    if doc.status != "Pending Approval":
        frappe.throw("Only Pending Approval Cost Breakdowns can be approved.")
    current = frappe.get_all("Design Cost Breakdown",
        filters={"design_code": doc.design_code, "status": "Approved"},
        fields=["name", "revision_no"], limit_page_length=2)
    if len(current) > 1:
        frappe.throw("Multiple approved costings exist. Contact the administrator.")
    if current and int(current[0].revision_no) >= int(doc.revision_no):
        frappe.throw("A newer approved revision already exists.")
    doc.status = "Approved"
    doc.approved_by = frappe.session.user
    doc.approved_on = now_datetime()
    doc.flags.cost_transition = "approve"
    doc.save(ignore_permissions=True)
    # Previous approval remains a complete audit snapshot. Only its workflow
    # marker changes, and only inside this approval transaction.
    if current:
        frappe.db.set_value("Design Cost Breakdown", current[0].name, {
            "status": "Superseded", "superseded_by": doc.name,
        }, update_modified=False)
        frappe.clear_document_cache("Design Cost Breakdown", current[0].name)
    return {"name": doc.name, "status": doc.status, "revision_no": doc.revision_no,
            "superseded": current[0].name if current else None}


@frappe.whitelist(methods=["POST"])
def cancel_approved_cost_breakdown(name, reason):
    """Revoke only the CURRENT approval while retaining all its priced lines.

    The old approval remains an auditable, immutable Cancelled document.
    Superseded revisions are not reapproved automatically. This endpoint does
    not edit production items, buying documents or milestones.
    """
    design, doc = _design_and_doc(name)
    _approval_access(design, doc)
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 500:
        frappe.throw("Provide a cancellation reason between 10 and 500 characters.")

    # Serialize with revision approval and creation on this same Design Code.
    frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                  (doc.design_code,))
    doc.reload()
    if doc.status != "Approved" or doc.superseded_by:
        frappe.throw("Only the current Approved Cost Breakdown can be cancelled.")
    if frappe.db.exists("Design Cost Breakdown", {
        "design_code": doc.design_code, "status": "Approved",
        "name": ["!=", doc.name],
    }):
        frappe.throw("Another Approved costing exists. Resolve duplicate approvals first.")

    doc.status = "Cancelled"
    doc.cancelled_by = frappe.session.user
    doc.cancelled_on = now_datetime()
    doc.cancellation_reason = reason
    doc.flags.cost_transition = "cancel"
    doc.save(ignore_permissions=True)
    return {
        "name": doc.name, "status": doc.status,
        "cancelled_by": doc.cancelled_by,
        "cancelled_on": str(doc.cancelled_on),
        "active_approval_remaining": False,
    }


@frappe.whitelist(methods=["POST"])
def create_cost_revision(source_name):
    design, source = _design_and_doc(source_name)
    _prepare_access(design, create=True)
    if source.status not in ("Approved", "Superseded", "Cancelled"):
        frappe.throw("Revisions may be created only from approved, superseded or cancelled costings.")
    # Calling before_insert() locks the design and rejects concurrent drafts.
    new = frappe.get_doc({
        "doctype": "Design Cost Breakdown",
        "design_code": source.design_code,
        "source_revision": source.name,
        "costing_method": source.costing_method,
        "quotation_date": nowdate(),
        "quotation_reference": source.quotation_reference,
        # Never copy an attachment automatically; its File belongs to the
        # source version, and must not become an editable new-version file.
        "quotation_attachment": None,
        "factory": source.factory,
        "currency": source.currency,
        "incoterm": source.incoterm,
        "exchange_rate_sar": source.exchange_rate_sar,
        "commercial_remarks": source.commercial_remarks,
    })
    for row in source.cost_components or []:
        new.append("cost_components", {
            key: row.get(key) for key in (
                "cost_category", "description", "applies_to", "variant_code",
                "cost_basis", "consumption", "uom", "unit_rate",
                "wastage_percent", "remarks"
            )
        })
    for row in source.price_qty_lines or []:
        new.append("price_qty_lines", {
            key: row.get(key) for key in (
                "variant_code", "production_key", "planned_item_code", "proposed_qty",
                "moq", "supplier_quoted_price", "negotiated_unit_price",
                "moq_exception_reason", "remarks"
            )
        })
    new.flags.cost_revision_clone = True
    new.insert(ignore_permissions=True)
    return {"name": new.name, "revision_no": new.revision_no, "status": new.status}


@frappe.whitelist()
def design_cost_defaults(design_code):
    design = frappe.get_doc("Design Code", design_code)
    if not _allowed_design(design) or not (_preparer(design) or _buyer()):
        frappe.throw("No access to commercial costing for this Design.", frappe.PermissionError)
    return {
        "design_code": design.name, "factory": design.factory,
        "merchandiser": design.assigned_merchandiser,
        "currency": design.production_currency,
        "variants": [{
            "variant_code": row.color_name or row.item_code,
            "planned_item_code": row.item_code, "production_key": row.production_key,
            "proposed_qty": row.quantity,
            "negotiated_unit_price": row.unit_cost,
        } for row in (design.production_items or [])][:200],
    }


@frappe.whitelist()
def cost_actions(name):
    design, doc = _design_and_doc(name)
    user = frappe.session.user
    preparer = _preparer(design, user)
    approver = _buyer(user) and (user == "Administrator" or
                                 user not in (doc.prepared_by, doc.submitted_by))
    return {
        "can_submit": preparer and doc.status in ("Draft", "Returned"),
        "can_return": approver and doc.status == "Pending Approval",
        "can_approve": approver and doc.status == "Pending Approval",
        "can_cancel": approver and doc.status == "Approved" and not doc.superseded_by,
        "can_revise": preparer and doc.status in ("Approved", "Superseded", "Cancelled"),
    }
