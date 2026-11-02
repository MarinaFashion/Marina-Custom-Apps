"""Internal provenance ledger for Frappe Role grants created by this module."""
import frappe
from frappe.model.document import Document

class DesignModuleManagedGrant(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Managed role grant history cannot be edited")
