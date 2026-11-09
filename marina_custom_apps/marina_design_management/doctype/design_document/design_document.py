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
        # A Design Document may include a primary file plus several files from
        # different designers. All files are evidence for the same assignments.
        files = ([self.attachment] if self.attachment else []) + [
            row.file for row in (self.get("additional_files") or [])
        ]
        if len(files) > 50:
            frappe.throw("Maximum 50 files per Design Document")
        if self.publication_status == "Published" and not files:
            frappe.throw("At least one valid ERPNext file is required for publication")
        if len(set(files)) != len(files) or not all(files):
            frappe.throw("Design Document files must be nonempty and unique")
        for file_url in files:
            if (not isinstance(file_url, str)
                    or not file_url.startswith(("/files/", "/private/files/"))
                    or ".." in file_url or "?" in file_url or "#" in file_url
                    or len(file_url) > 500):
                frappe.throw("Attach a valid ERPNext file before publishing")
        if files:
            found = {
                row.file_url for row in frappe.get_all(
                    "File", filters={"file_url": ["in", files]},
                    fields=["file_url"], limit_page_length=51)
            }
            if any(url not in found for url in files):
                frappe.throw("One or more attached files do not exist in ERPNext Files")
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
            def _file_rows(doc):
                return sorted((row.file or "", row.designer or "",
                               row.description or "")
                              for row in (doc.get("additional_files") or []))
            if (before.publication_status == "Published"
                    and _file_rows(before) != _file_rows(self)):
                frappe.throw(
                    "Published additional files cannot be edited. "
                    "Use Replace Published File to issue a new version."
                )
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
        # File uploads on new forms can be attached to temporary names.
        # Reassociate ONLY the current user's temporary File records after
        # the document receives its permanent identifier. Never take over
        # files attached to other saved documents.
        file_urls = ([self.attachment] if self.attachment else []) + [
            r.file for r in (self.get("additional_files") or []) if r.file
        ]
        if file_urls:
            uploaded = frappe.get_all("File",
                filters={"file_url": ["in", file_urls]},
                fields=["name", "owner", "attached_to_doctype",
                        "attached_to_name", "file_url"],
                limit_page_length=51)
            for record in uploaded:
                if (record.owner == frappe.session.user
                        and record.attached_to_doctype in (
                            "Design Document", "Design Document Additional File")
                        and (record.attached_to_name or "").startswith("new-")):
                    frappe.db.set_value("File", record.name, {
                        "attached_to_doctype": "Design Document",
                        "attached_to_name": self.name,
                        "attached_to_field": "attachment" if record.file_url == self.attachment
                            else "additional_files",
                    }, update_modified=False)
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
