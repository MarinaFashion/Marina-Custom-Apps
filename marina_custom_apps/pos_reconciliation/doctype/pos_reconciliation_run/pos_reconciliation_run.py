from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from marina_custom_apps.pos_reconciliation.reconciliation_engine import execute_run


class POSReconciliationRun(Document):
    def validate(self):
        self.validate_date_range()

    def validate_date_range(self):
        if not self.from_date or not self.to_date:
            frappe.throw(_("From Date and To Date are required."))
        if getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))


@frappe.whitelist()
def run_reconciliation(run_name):
    return execute_run(run_name)
