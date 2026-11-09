"""Immutable version replacement for published Design Documents.

A replacement creates a NEW Published Design Document. Existing milestone
execution/custody event links remain attached to the old document and file.
No rewrite of historical evidence references is permitted.
"""
import frappe

from marina_custom_apps.design_management.security.document_access import can_manage_documents
from marina_custom_apps.design_management.security.role_access import can_action


def _allowed(doc, actor):
    return bool(
        doc.publication_status == "Published"
        and not doc.superseded_by
        and can_action("Replace Published Document", actor)
        and can_manage_documents(actor)
        and frappe.has_permission("Design Document", "read", doc=doc, user=actor)
        and frappe.has_permission("Design Document", "write", doc=doc, user=actor)
        and frappe.has_permission("Design Document", "create", user=actor)
    )


@frappe.whitelist()
def can_replace_published_file(document_name):
    """UI hint only. The POST endpoint repeats every check under lock."""
    if not isinstance(document_name, str) or not 0 < len(document_name) <= 140:
        return False
    doc = frappe.get_doc("Design Document", document_name)
    return _allowed(doc, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def replace_published_file(document_name, file_url, reason, replace_target=None):
    """Publish a new immutable revision, superseding the prior document.

    The source is locked and its historical evidence remains unchanged.
    File replacement is a separate document revision (not editing in place).
    """
    actor = frappe.session.user
    if not isinstance(document_name, str) or not 0 < len(document_name) <= 140:
        frappe.throw("Select a valid published Design Document")
    if not isinstance(file_url, str) or not 0 < len(file_url) <= 500:
        frappe.throw("Attach a replacement File")
    if (not file_url.startswith(("/files/", "/private/files/"))
            or ".." in file_url or "?" in file_url or "#" in file_url):
        frappe.throw("Select a valid ERPNext File URL")
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if not 10 <= len(reason) <= 500:
        frappe.throw("Provide a revision reason (10–500 characters)")

    frappe.db.sql(
        "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
        (document_name,),
    )
    previous = frappe.get_doc("Design Document", document_name)
    if not _allowed(previous, actor):
        frappe.throw(
            "Replace Published Document action and Design Document "
            "Read/Create/Edit permissions are required",
            frappe.PermissionError,
        )
    old_urls = ([previous.attachment] if previous.attachment else []) + [
        row.file for row in (previous.get("additional_files") or [])
    ]
    target = replace_target or previous.attachment
    if target not in old_urls:
        frappe.throw("Select an existing file in this published document")
    if file_url in old_urls:
        frappe.throw("Select a new replacement file, not one already in this document")

    # Only an actual ERPNext File controlled by the acting user can be used.
    # Prevent pointing to another document's existing stored attachment.
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw("The replacement file does not exist in ERPNext Files")
    frappe.db.sql("SELECT name FROM `tabFile` WHERE name=%s FOR UPDATE", (file_name,))
    uploaded = frappe.get_doc("File", file_name)
    if actor != "Administrator" and "System Manager" not in frappe.get_roles(actor):
        if uploaded.owner != actor:
            frappe.throw("You may only use a file uploaded by you", frappe.PermissionError)
    if (uploaded.attached_to_doctype == "Design Document"
            and uploaded.attached_to_name
            and not uploaded.attached_to_name.startswith("new-")
            and uploaded.attached_to_name != document_name):
        frappe.throw("Replacement file is attached to another saved Design Document")
    if frappe.db.exists("Design Document", {"attachment": file_url}):
        frappe.throw("This file is already used by another Design Document")

    revision = frappe.get_doc({
        "doctype": "Design Document",
        "document_title": previous.document_title,
        "document_type": previous.document_type,
        "tech_pack_mood_board": previous.tech_pack_mood_board,
        "related_milestone_type": previous.related_milestone_type,
        "description": previous.description,
        "attachment": (file_url if target == previous.attachment
                       else previous.attachment),
        "publication_status": "Draft",
        "supersedes_document": previous.name,
        "revision_reason": reason,
    })
    for row in previous.get("additional_files") or []:
        revision.append("additional_files", {
            "designer": row.designer,
            "file": file_url if row.file == target else row.file,
            "description": row.description,
        })
    for assignment in previous.get("assignments") or []:
        revision.append("assignments", {
            "design_code": assignment.design_code,
            "target_milestone_type": assignment.target_milestone_type,
            "mood_board": assignment.mood_board,
        })
    revision.flags.document_revision_action = True
    revision.insert()
    # Publish within the same transaction; do not require a separate
    # Publish action because the Replace action is the explicit authority.
    from frappe.utils import now_datetime
    revision.publication_status = "Published"
    revision.published_by = actor
    revision.published_on = now_datetime()
    revision.flags.document_publication_action = True
    revision.flags.document_revision_action = True
    revision.save()
    # Designer file mapping is carried forward exactly. Existing Design
    # assignments are copied above, and old milestone evidence is untouched.
    # Future Design Codes will use the new published version only.

    # The old document is never saved or changed other than its reference to
    # the replacement. Its attachment, publication and evidence remain intact.
    frappe.db.set_value(
        "Design Document", previous.name, "superseded_by", revision.name,
        update_modified=False,
    )
    # Reassociate an uploaded temporary File with its final Design Document.
    # This does not move, overwrite or delete the physical file.
    frappe.db.set_value("File", uploaded.name, {
        "attached_to_doctype": "Design Document",
        "attached_to_name": revision.name,
        "attached_to_field": "attachment",
    })
    previous.add_comment(
        "Info",
        text=("Published file superseded by " + revision.name + " by " + actor
              + ". Revision reason: " + reason
              + ". Historical milestone evidence remains on this version."),
    )
    revision.add_comment(
        "Info",
        text=("Published revision replacing " + previous.name + " by " + actor
              + ". Revision reason: " + reason),
    )
    return {
        "previous": previous.name,
        "replacement": revision.name,
        "publication_status": revision.publication_status,
        "linked_designs": len(revision.assignments or []),
        "files": (1 if revision.attachment else 0) + len(revision.additional_files or []),
    }
