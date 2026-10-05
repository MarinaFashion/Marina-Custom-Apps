from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class POSAccountingPosting(Document):
    def validate(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import (
            validate_posting_document,
        )

        validate_posting_document(self)

    def before_submit(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import (
            validate_posting_before_submit,
        )

        validate_posting_before_submit(self)

    def on_submit(self):
        from marina_custom_apps.pos_reconciliation.accounting_service import (
            JOURNAL_ENTRY_MODE_SUBMIT,
            create_journal_entry,
        )

        journal_entry = create_journal_entry(self)
        creation_mode = self.journal_entry_creation_mode or "Draft"

        posting_status = "Posted" if cint(journal_entry.docstatus) == 1 else "Journal Entry Draft"
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "journal_entry": journal_entry.name,
                "posting_status": posting_status,
            },
            update_modified=False,
        )
        self.journal_entry = journal_entry.name
        self.posting_status = posting_status

        # Journal Entry on_submit performs the authoritative Posted transition.
        if creation_mode == JOURNAL_ENTRY_MODE_SUBMIT and cint(journal_entry.docstatus) != 1:
            frappe.throw("Journal Entry was configured for automatic submission but remains in Draft.")

    def before_cancel(self):
        if not self.journal_entry or not frappe.db.exists("Journal Entry", self.journal_entry):
            return

        journal_entry_name = self.journal_entry
        journal_entry = frappe.get_doc("Journal Entry", journal_entry_name)

        # POS Accounting Posting is the authoritative parent. Temporarily
        # remove its Link so Frappe permits cancellation of the generated JE.
        frappe.db.set_value(
            self.doctype,
            self.name,
            "journal_entry",
            None,
            update_modified=False,
        )

        try:
            if journal_entry.docstatus == 1:
                journal_entry.cancel()
            elif journal_entry.docstatus == 0:
                frappe.delete_doc(
                    "Journal Entry",
                    journal_entry.name,
                    ignore_permissions=True,
                    force=True,
                )
        except Exception:
            frappe.db.set_value(
                self.doctype,
                self.name,
                "journal_entry",
                journal_entry_name,
                update_modified=False,
            )
            raise

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
