import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, sanitize_html, strip_html_tags


LOCKED_STATUSES = {"Published", "Superseded"}
ADVANCED_HTML_MODE = "Advanced HTML"
LOCAL_IMAGE_PREFIXES = ("/files/", "/private/files/")
_IMAGE_SRC_RE = re.compile(
    r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def sanitize_sop_html(value):
    """Sanitize HTML and restrict images to ERPNext File URLs."""
    sanitized = sanitize_html(value or "", always_sanitize=True)

    for src in _IMAGE_SRC_RE.findall(sanitized):
        src = (src or "").strip()
        lower = src.lower()
        if lower.startswith(("http://", "https://", "//", "data:")):
            frappe.throw(
                _(
                    "Advanced HTML images must be uploaded to ERPNext and use "
                    "/files/ or /private/files/ URLs."
                )
            )
        if src and not src.startswith(LOCAL_IMAGE_PREFIXES):
            frappe.throw(
                _("Unsupported image URL {0}. Upload the image to ERPNext Files first.").format(
                    frappe.bold(src)
                )
            )

    return sanitized


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

        self.content_mode = self.content_mode or "Standard Rich Text"

        if self.content_mode == ADVANCED_HTML_MODE:
            self.html_content = sanitize_sop_html(self.html_content)

        # Draft versions are working documents and may be incomplete.
        # Completeness becomes mandatory when the version leaves Draft.
        if self.status != "Draft":
            self.validate_content_completeness()

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

    def validate_content_completeness(self):
        if self.content_mode == ADVANCED_HTML_MODE:
            sanitized = sanitize_sop_html(self.html_content)
            if not strip_html_tags(sanitized or "").strip():
                frappe.throw(_("Advanced HTML Body is required before review."))
        else:
            self._validate_language_content()

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
