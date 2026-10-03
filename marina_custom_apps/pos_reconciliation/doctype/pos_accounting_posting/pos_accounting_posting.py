from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class POSAccountingPosting(Document):
    def validate(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import validate_posting_document

        validate_posting_document(self)

    def before_submit(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import validate_posting_before_submit

        validate_posting_before_submit(self)

    def on_submit(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import (
            create_and_submit_journal_entry,
            mark_posting_posted,
        )

        journal_entry = create_and_submit_journal_entry(self)
        posted_on = mark_posting_posted(self, journal_entry)
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "journal_entry": journal_entry.name,
                "posting_status": "Posted",
                "posted_by": frappe.session.user,
                "posted_on": posted_on,
            },
            update_modified=False,
        )
        self.journal_entry = journal_entry.name
        self.posting_status = "Posted"
        self.posted_by = frappe.session.user
        self.posted_on = posted_on

    def before_cancel(self):
        if not self.journal_entry or not frappe.db.exists("Journal Entry", self.journal_entry):
            return
        journal_entry = frappe.get_doc("Journal Entry", self.journal_entry)
        if journal_entry.docstatus == 1:
            journal_entry.cancel()

    def on_cancel(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import release_posting

        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "posting_status": "Cancelled",
                "cancelled_by": frappe.session.user,
                "cancelled_on": now_datetime(),
            },
            update_modified=False,
        )
        release_posting(self.name, self.journal_entry)
