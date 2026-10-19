from frappe.model.document import Document


class BankStatementReconciliationMatch(Document):
    def on_trash(self):
        import frappe
        from frappe import _
        if not getattr(frappe.flags, "allow_bank_reconciliation_match_delete", False):
            frappe.throw(_("Use Reverse Reconciliation instead of deleting this match directly."), frappe.PermissionError)
