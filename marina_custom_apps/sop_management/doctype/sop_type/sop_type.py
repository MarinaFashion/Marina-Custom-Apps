import frappe
from frappe.model.document import Document
from frappe import _


class SOPType(Document):
    def validate(self):
        self.type_name = (self.type_name or "").strip()
        if not self.type_name:
            frappe.throw(_("SOP Type Name is required."))
        if self.parent_sop_type and self.parent_sop_type == self.name:
            frappe.throw(_("An SOP Type cannot be its own parent."))
