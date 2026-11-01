"""Write-once audit of authorized Design/Milestone cleanup."""
import frappe
from frappe.model.document import Document

class DesignCleanupLog(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Design Cleanup Log is immutable")
    def on_trash(self):
        frappe.throw("Design Cleanup Log cannot be deleted")
