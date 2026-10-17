from frappe import _
import frappe
from frappe.model.document import Document


class BankReconciliationExclusion(Document):
    def validate(self):
        if not self.flags.get("allow_exclusion_change"):
            frappe.throw(_("Use the Bank Statement Reconciliation exclusion and restoration actions to change this record."))

    def on_trash(self):
        frappe.throw(_("Bank reconciliation exclusion audit records must not be deleted."))
