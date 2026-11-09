"""Static Design Document assignments, protected file and assignment audit metadata."""
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from marina_custom_apps.design_management.security.document_access import can_manage_documents, can_assign_design


class DesignDocument(Document):
    def before_validate(self):
        if self.is_new():
            self.added_by = frappe.session.user
            self.added_on = now_datetime()
        self.assignment_count = len(self.assignments or [])

    def validate(self):
        user = frappe.session.user
        if not can_manage_documents(user):
            frappe.throw("Not authorized to manage Design Documents", frappe.PermissionError)
        if not frappe.db.get_value("Design Document Type", self.document_type, "is_active"):
            frappe.throw("Document Type must be active")
        # Draft Design Documents can be saved without an uploaded file.
        # Published documents (including direct API saves) must always have
        # a valid ERPNext attachment, verified independently at publication.
        if self.attachment or self.publication_status == "Published":
            if (not self.attachment
                    or not self.attachment.startswith(("/files/", "/private/files/"))
                    or ".." in self.attachment or "?" in self.attachment
                    or "#" in self.attachment):
                frappe.throw("Attach a valid ERPNext file before publishing")
            if not frappe.db.exists("File", {"file_url": self.attachment}):
                frappe.throw("The selected file does not exist in ERPNext Files")
        before = self.get_doc_before_save() if not self.is_new() else None
        # Revision metadata is written only by the controlled publication
        # endpoint. Read-only fields must also be protected server-side.
        revision_fields = ("supersedes_document", "superseded_by", "revision_reason")
        if self.is_new():
            if (any(self.get(k) for k in revision_fields)
                    and not self.flags.get("document_revision_action")):
                frappe.throw("Use Replace Published File to create a document revision")
        elif before:
            if (any(self.get(k) != before.get(k) for k in revision_fields)
                    and not self.flags.get("document_revision_action")):
                frappe.throw("Document revision history is immutable")
            if before.superseded_by:
                frappe.throw("Replaced published versions cannot be edited")
        if self.publication_status not in ("Draft", "Published", None, ""):
            frappe.throw("Invalid publication state")
        if self.publication_status == "Published" and not self.flags.get(
                "document_publication_action"):
            if not before or before.publication_status != "Published":
                frappe.throw("Use Publish Document to publish a document")
        if before:
            changed_publication = any(
                str(self.get(k) or "") != str(before.get(k) or "")
                for k in ("publication_status", "published_by", "published_on")
            )
            if changed_publication and not self.flags.get("document_publication_action"):
                frappe.throw("Use Publish Document to publish a document")
            if before.publication_status == "Published":
                if self.document_type != before.document_type or (
                    self.related_milestone_type != before.related_milestone_type):
                    frappe.throw("Published document type and milestone mapping are immutable")
                from marina_custom_apps.design_management.clean_milestones.document_revisions import assignment_delta
                added, removed, remapped = assignment_delta(
                    [r.as_dict() for r in before.assignments or []],
                    [r.as_dict() for r in self.assignments or []],
                )
                # Appending a new Design Code is safe: published file, prior
                # mappings and historical evidence remain exactly as before.
                if remapped:
                    frappe.throw("Existing published milestone assignments cannot be changed. "
                                 "Unpublish for revision if it is not already used as evidence.")
                if removed and getattr(frappe.flags, "marina_published_detach_doc", None) != self.name:
                    frappe.throw("Use Remove Published Assignment to unlink existing designs")
        if before:
            # The working copy may be corrected before publication while it
            # has no Design Code assignments. Published or linked documents
            # retain their immutable file for evidence/audit integrity.
            if before.attachment and self.attachment != before.attachment:
                if (before.publication_status != "Draft"
                        or self.publication_status != "Draft"
                        or before.get("assignments")
                        or self.get("assignments")):
                    frappe.throw(
                        "Cannot replace a file on a published or linked Design Document"
                    )
                if (frappe.db.exists("Design Milestone Execution",
                                    {"evidence_document": self.name})
                        or frappe.db.exists("Design Milestone Custody Event",
                                            {"evidence_document": self.name})):
                    frappe.throw("Cannot replace a document used as milestone evidence")
            if self.added_by != before.added_by or str(self.added_on) != str(before.added_on):
                frappe.throw("Upload audit fields cannot be modified")
        previous = {row.design_code: row for row in before.assignments} if before else {}
        selected = set()
        from marina_custom_apps.design_management.clean_milestones.document_revisions import (
            default_assignment_milestone,
        )
        for row in self.assignments or []:
            if not row.design_code or row.design_code in selected:
                frappe.throw("Each selected Design Code must be unique")
            selected.add(row.design_code)
            # Newly added styles inherit the document's Related Milestone Type
            # unless explicitly overridden. Preserve old blank rows, including
            # historical Published assignments, without silent remapping.
            row.target_milestone_type = default_assignment_milestone(
                row.target_milestone_type, self.related_milestone_type,
                existing=row.design_code in previous,
            )
            old_assignment = previous.get(row.design_code)
            changed_mapping = (
                not old_assignment or
                old_assignment.target_milestone_type != row.target_milestone_type
            )
            # For unchanged rows on a shared Published document, reuse its
            # saved values. This avoids repeated Design/Milestone queries for
            # every unrelated design when appending a single new style.
            if changed_mapping:
                if not frappe.db.exists("Design Code", row.design_code):
                    frappe.throw("Unknown Design Code: " + row.design_code)
                if not can_assign_design(user, row.design_code):
                    frappe.throw("Not permitted to assign document to " +
                                 row.design_code, frappe.PermissionError)
                if row.target_milestone_type and not frappe.db.exists(
                        "Design Milestone Type", row.target_milestone_type):
                    frappe.throw("Unknown target milestone: " +
                                 row.target_milestone_type)
                row.mood_board = frappe.db.get_value(
                    "Design Code", row.design_code, "mood_board")
            else:
                # The Design Code's Mood Board cannot change after creation.
                row.mood_board = old_assignment.mood_board
            if row.design_code in previous:
                old = previous[row.design_code]
                row.assigned_by = old.assigned_by
                row.assigned_on = old.assigned_on
            else:
                row.assigned_by = user
                row.assigned_on = now_datetime()
        for code in set(previous) - selected:
            if not can_assign_design(user, code):
                frappe.throw("Not permitted to remove assignment for " + code, frappe.PermissionError)
        # Assignment filters are only for previews; no future matching Design Code inherits a file.

    def on_update(self):
        # Frappe Version also tracks the full child-table change. A readable
        # timeline event makes appended designs easy to find in the document.
        previous = self.get_doc_before_save()
        if (not previous or previous.publication_status != "Published"
                or self.publication_status != "Published"):
            return
        from marina_custom_apps.design_management.clean_milestones.document_revisions import assignment_delta
        added, _, _ = assignment_delta(
            [r.as_dict() for r in previous.assignments or []],
            [r.as_dict() for r in self.assignments or []],
        )
        if added:
            self.add_comment("Info", text="Added designs to published document: " +
                             ", ".join(added))

    def on_trash(self):
        # Recheck at mutation time. Draft documents may be deleted only when
        # unlinked and not referenced as current or historical evidence.
        if self.publication_status != "Draft":
            frappe.throw("Only Draft Design Documents can be deleted")
        if self.get("assignments") or frappe.db.exists(
            "Design Document Assignment",
            {"parent": self.name, "parenttype": "Design Document"}
        ):
            frappe.throw("Remove all Design Code assignments before deleting this document")
        if (frappe.db.exists("Design Milestone Execution",
                             {"evidence_document": self.name})
                or frappe.db.exists("Design Milestone Custody Event",
                                    {"evidence_document": self.name})):
            frappe.throw("Cannot delete a Design Document used as milestone evidence")
