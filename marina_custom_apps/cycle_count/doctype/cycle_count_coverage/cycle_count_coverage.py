import frappe
from frappe import _
from frappe.model.document import Document

class CycleCountCoverage(Document):
    def validate(self):
        if not self.company or not self.store_warehouse or not self.item_template:
            return
        duplicate = frappe.db.get_value("Cycle Count Coverage", {
            "company": self.company, "store_warehouse": self.store_warehouse,
            "item_template": self.item_template, "name": ["!=", self.name or ""]
        }, "name")
        if duplicate:
            frappe.throw(_("Coverage already exists for {0} at {1}.").format(self.item_template, self.store_warehouse))
