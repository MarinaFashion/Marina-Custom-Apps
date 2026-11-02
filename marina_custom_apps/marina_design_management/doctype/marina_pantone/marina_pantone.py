import frappe
from frappe.model.document import Document

class MarinaPantone(Document):
    def validate(self):
        self.pantone_code = (self.pantone_code or "").strip().upper()
        if not self.pantone_code:
            frappe.throw("Pantone Code is mandatory")
