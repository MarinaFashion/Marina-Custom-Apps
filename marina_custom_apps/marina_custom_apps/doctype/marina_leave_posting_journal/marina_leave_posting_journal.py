"""Reserved posting record; created only by a future audited posting service."""
import frappe
from frappe import _
from frappe.model.document import Document


class MarinaLeavePostingJournal(Document):
    def before_insert(self):
        if not getattr(self.flags, "marina_authorized_posting_service", False):
            frappe.throw(_("Journal creation is not enabled yet."), frappe.PermissionError)

    def validate(self):
        if not getattr(self.flags, "marina_authorized_posting_service", False):
            frappe.throw(_("Journal updates are not enabled yet."), frappe.PermissionError)
        if self.leave_type != "Paid Leave":
            frappe.throw(_("Only Paid Leave is supported by this journal"))
