import frappe
from frappe.model.document import Document


class DesignMilestoneExecution(Document):
    def validate(self):
        frappe.throw("Use controlled Release 22 actions", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Release 22 records are protected")
