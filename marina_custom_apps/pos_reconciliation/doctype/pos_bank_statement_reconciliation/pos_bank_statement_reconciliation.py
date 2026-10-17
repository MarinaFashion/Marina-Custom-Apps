from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class POSBankStatementReconciliation(Document):
    def validate(self):
        if not self.bank_account:
            frappe.throw(_("Bank Account is required."))
        if not self.from_date or not self.to_date:
            frappe.throw(_("From Date and To Date are required."))
        if getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))
        if self.tolerance is None:
            self.tolerance = 0.01


@frappe.whitelist()
def run_statement_reconciliation(name):
    doc = frappe.get_doc("POS Bank Statement Reconciliation", name)
    doc.check_permission("write")

    from marina_custom_apps.pos_reconciliation.bank_statement_reconciliation_service import (
        execute_statement_reconciliation,
    )

    return execute_statement_reconciliation(doc)
