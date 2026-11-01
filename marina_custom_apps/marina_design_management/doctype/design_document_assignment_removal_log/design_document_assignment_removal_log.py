import frappe
from frappe.model.document import Document

class DesignDocumentAssignmentRemovalLog(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Removal audit is immutable")
    def on_trash(self):
        frappe.throw("Removal audit cannot be deleted")
