import frappe
from frappe import _
from frappe.model.document import Document


class SOPDocument(Document):
    def validate(self):
        self.title_en = (self.title_en or "").strip()
        self.title_ar = (self.title_ar or "").strip()

        if not self.title_en and not self.title_ar:
            frappe.throw(_("Enter an English or Arabic title."))

        if self.language == "English" and not self.title_en:
            frappe.throw(_("English title is required for an English SOP."))
        if self.language == "Arabic" and not self.title_ar:
            frappe.throw(_("Arabic title is required for an Arabic SOP."))

        self.display_title = self.title_en or self.title_ar

        if self.parent_sop_document and self.parent_sop_document == self.name:
            frappe.throw(_("An SOP Document cannot be its own parent."))

        # Status/current publication are controlled only by the server-side
        # publication service. Read-only form fields are not a security gate:
        # REST/API writes must not be able to self-publish or unpublish an SOP.
        before = self.get_doc_before_save()
        if not before:
            self.status = "Draft"
            self.current_version = None
            self.current_version_no = 0
        elif not frappe.flags.in_sop_publication:
            self.status = before.status
            self.current_version = before.current_version
            self.current_version_no = before.current_version_no

    def on_trash(self):
        if self.status == "Published" or self.current_version:
            frappe.throw(
                _("A published SOP Document cannot be deleted. Archive it instead.")
            )
