import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


LOCKED_STATUSES = {"Published", "Superseded"}


class SOPVersion(Document):
    def before_insert(self):
        if not self.version_no:
            last = frappe.db.sql(
                '''
                select coalesce(max(version_no), 0)
                from `tabSOP Version`
                where sop_document = %s
                ''',
                (self.sop_document,),
            )[0][0] or 0
            self.version_no = cint(last) + 1

    def validate(self):
        if not self.sop_document:
            frappe.throw(_("SOP Document is required."))

        parent = frappe.get_doc("SOP Document", self.sop_document)
        if not self.language:
            self.language = parent.language or "Bilingual"

        duplicate = frappe.db.exists(
            "SOP Version",
            {
                "sop_document": self.sop_document,
                "version_no": self.version_no,
                "name": ["!=", self.name or ""],
            },
        )
        if duplicate:
            frappe.throw(
                _("Version {0} already exists for {1}.").format(
                    self.version_no, self.sop_document
                )
            )

        self._validate_language_content()

        before = self.get_doc_before_save()

        # Client-side read_only is UX only. Enforce lifecycle transitions on
        # the server so Editor/API users cannot jump directly to Approved or
        # Published status outside the controlled actions in sop_management.api.
        if not frappe.flags.in_sop_publication:
            if not before and self.status != "Draft":
                frappe.throw(_("A new SOP Version must start in Draft status."))
            if before and self.status != before.status:
                frappe.throw(
                    _("Use the SOP workflow actions to change Version status.")
                )

        if before and before.status in LOCKED_STATUSES and not frappe.flags.in_sop_publication:
            frappe.throw(
                _("Published or superseded SOP Versions are immutable. Create a new version.")
            )

    def on_trash(self):
        if self.status in LOCKED_STATUSES:
            frappe.throw(
                _("Published or superseded SOP Versions cannot be deleted.")
            )

    def _validate_language_content(self):
        if not self.sections:
            frappe.throw(_("Add at least one SOP Section."))

        for idx, row in enumerate(self.sections, start=1):
            if self.language in ("English", "Bilingual"):
                if not (row.heading_en or row.content_en):
                    frappe.throw(
                        _("Section {0}: English heading or content is required.").format(idx)
                    )
            if self.language in ("Arabic", "Bilingual"):
                if not (row.heading_ar or row.content_ar):
                    frappe.throw(
                        _("Section {0}: Arabic heading or content is required.").format(idx)
                    )
