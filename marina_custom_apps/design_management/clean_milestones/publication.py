"""Publish documents without changing any milestone status.

Publication and milestone progression are deliberately independent. A manual
milestone transition separately validates a Published document and, if needed,
explicitly confirms its Design Code assignment.
"""
import frappe
from frappe.utils import now_datetime
from marina_custom_apps.design_management.security.role_access import can_action
from marina_custom_apps.design_management.security.document_access import can_manage_documents


def _publication_document(document_name):
    actor = frappe.session.user
    if not can_action("Publish Document", actor) or not can_manage_documents(actor):
        frappe.throw("Publish Document Module Action required", frappe.PermissionError)
    frappe.db.sql("SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
                  (document_name,))
    doc = frappe.get_doc("Design Document", document_name)
    doc.check_permission("write")
    return doc


@frappe.whitelist()
def can_unpublish_document(document_name):
    """UI capability only; mutation independently rechecks the permissions."""
    actor = frappe.session.user
    if not can_action("Publish Document", actor) or not can_manage_documents(actor):
        return False
    doc = frappe.get_doc("Design Document", document_name)
    if (not doc.has_permission("write") or doc.publication_status != "Published"
            or doc.superseded_by):
        return False
    return not bool(
        frappe.db.exists("Design Milestone Execution",
                         {"evidence_document": doc.name})
        or frappe.db.exists("Design Milestone Custody Event",
                            {"evidence_document": doc.name})
    )


@frappe.whitelist(methods=["POST"])
def unpublish_document(document_name):
    """Controlled revision opening, only before the document is used as evidence.

    A published document already attached to any milestone remains published
    to preserve completed approval evidence. Adding designs is permitted
    directly to those published documents without this action.
    """
    doc = _publication_document(document_name)
    if doc.publication_status != "Published" or doc.superseded_by:
        frappe.throw("A superseded published version cannot be unpublished")
    if (frappe.db.exists("Design Milestone Execution",
                         {"evidence_document": doc.name})
            or frappe.db.exists("Design Milestone Custody Event",
                                {"evidence_document": doc.name})):
        frappe.throw("This published document is already used as milestone evidence. "
                     "Add new Design Codes to the published document without unpublishing it.")
    doc.publication_status = "Draft"
    doc.published_by = None
    doc.published_on = None
    doc.flags.document_publication_action = True
    doc.save(ignore_permissions=True)
    doc.add_comment("Info", text="Unpublished for assignment revision by " +
                    frappe.session.user)
    return {"document": document_name, "publication_status": "Draft"}


@frappe.whitelist(methods=["POST"])
def publish_document(document_name):
    actor = frappe.session.user
    doc = _publication_document(document_name)
    if doc.publication_status == "Published":
        return {"published": document_name, "already_published": True}
    if not (doc.attachment or any(row.file for row in (doc.get("additional_files") or []))):
        frappe.throw("Attach at least one file before publishing")
    for assignment in doc.assignments:
        if not (assignment.target_milestone_type or doc.related_milestone_type):
            frappe.throw("Select the supported milestone for every Design Code assignment")
    if doc.document_type == "Tech Pack" and doc.tech_pack_mood_board:
        from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import (
            assert_unique_published_designer_files,
        )
        assert_unique_published_designer_files(doc)
    doc.publication_status = "Published"
    doc.published_by = actor
    doc.published_on = now_datetime()
    doc.flags.document_publication_action = True
    doc.save(ignore_permissions=True)
    if doc.document_type == "Tech Pack" and doc.tech_pack_mood_board:
        from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import (
            link_published_document,
        )
        link_published_document(doc)
    return {"published": document_name, "already_published": False}
