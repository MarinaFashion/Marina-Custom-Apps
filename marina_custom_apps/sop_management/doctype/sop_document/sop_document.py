import frappe
from frappe import _
from frappe.model.document import Document

AUDIENCE_TYPES = {"Designation", "Department", "Employee", "User"}

class SOPDocument(Document):
    def validate(self):
        self.title_en = (self.title_en or "").strip()
        self.title_ar = (self.title_ar or "").strip()
        self.document_no = (self.document_no or "").strip()
        self.visibility = self.visibility or "Everyone"

        if not self.title_en and not self.title_ar:
            frappe.throw(_("Enter an English or Arabic title."))
        if self.language == "English" and not self.title_en:
            frappe.throw(_("English title is required for an English SOP."))
        if self.language == "Arabic" and not self.title_ar:
            frappe.throw(_("Arabic title is required for an Arabic SOP."))

        self.display_title = self.title_en or self.title_ar
        if self.parent_sop_document and self.parent_sop_document == self.name:
            frappe.throw(_("An SOP Document cannot be its own parent."))

        if self.document_no:
            duplicate = frappe.db.exists("SOP Document", {
                "document_no": self.document_no,
                "name": ["!=", self.name or ""],
            })
            if duplicate:
                frappe.throw(_("Document No. {0} is already used.").format(frappe.bold(self.document_no)))

        self.validate_access_configuration(False)

        before = self.get_doc_before_save()
        if not before:
            self.status = "Draft"
            self.current_version = None
            self.current_version_no = 0
        else:
            if before.current_version and self.document_no != (before.document_no or ""):
                # v0.46.0 backfills legacy published SOPs with their internal
                # Frappe name (for example SOP-00001). Permit exactly one
                # business-number replacement from that migration placeholder.
                # After a real business Document No. is assigned, it is locked.
                legacy_placeholder = (before.document_no or "") == before.name
                if not legacy_placeholder:
                    frappe.throw(_("Document No. is locked after first publication."))
            if not frappe.flags.in_sop_publication:
                self.status = before.status
                self.current_version = before.current_version
                self.current_version_no = before.current_version_no

    def validate_access_configuration(self, require_audience=False):
        if self.visibility not in {"Everyone", "Restricted"}:
            frappe.throw(_("Visibility must be Everyone or Restricted."))

        for fieldname, label in (("applicable_for", _("Applicable For")),("allowed_audience", _("Allowed Audience"))):
            seen=set()
            for row in self.get(fieldname) or []:
                if row.audience_type not in AUDIENCE_TYPES:
                    frappe.throw(_("{0} row {1}: invalid audience type.").format(label,row.idx))
                if not row.target:
                    frappe.throw(_("{0} row {1}: Target is required.").format(label,row.idx))
                key=(row.audience_type,row.target)
                if key in seen:
                    frappe.throw(_("{0}: duplicate {1} / {2}.").format(label,*key))
                seen.add(key)

        if require_audience and self.visibility=="Restricted" and not (self.allowed_audience or self.applicable_for):
            frappe.throw(_("Restricted SOPs require an Allowed Audience or Applicable For row."))

    def on_trash(self):
        if self.status == "Published" or self.current_version:
            frappe.throw(_("A published SOP Document cannot be deleted. Archive it instead."))