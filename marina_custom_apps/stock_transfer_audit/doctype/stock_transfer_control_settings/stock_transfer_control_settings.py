import frappe
from frappe import _
from frappe.model.document import Document

from marina_custom_apps.stock_transfer_audit.audit_policy import (
    DEFAULT_AUDIT_PROCESS_START_DATE,
    as_date,
    start_date_change_issue,
)


def get_audit_process_start_date():
    value = frappe.db.get_single_value(
        "Stock Transfer Control Settings", "audit_process_start_date"
    )
    return as_date(value) or DEFAULT_AUDIT_PROCESS_START_DATE


class StockTransferControlSettings(Document):
    def validate(self):
        self.audit_process_start_date = (
            as_date(self.audit_process_start_date)
            or DEFAULT_AUDIT_PROCESS_START_DATE
        )

        before = self.get_doc_before_save()
        previous = as_date(before.get("audit_process_start_date")) if before else None
        current = as_date(self.audit_process_start_date)
        issue = start_date_change_issue(
            previous,
            current,
            bool(frappe.db.exists("Stock Transfer Audit Record")),
        )
        if issue:
            frappe.throw(_(issue))
