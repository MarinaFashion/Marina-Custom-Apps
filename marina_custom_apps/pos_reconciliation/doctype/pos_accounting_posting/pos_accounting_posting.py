from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, cstr, now_datetime


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
                # Internal parent -> child cancellation context.
                journal_entry.flags.pos_accounting_posting_cancel = self.name
                journal_entry.cancel()
            elif journal_entry.docstatus == 0:
                frappe.delete_doc(
                    "Journal Entry",
                    journal_entry.name,
                    ignore_permissions=True,
                    force=True,
                )
        except Exception:
            frappe.db.set_value(self.doctype, self.name, "journal_entry", journal_entry_name, update_modified=False)
            raise

        if frappe.db.exists("Journal Entry", journal_entry_name):
            frappe.db.set_value(self.doctype, self.name, "journal_entry", journal_entry_name, update_modified=False)

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

    def on_trash(self):
        journal_entry_name = self.journal_entry
        if not journal_entry_name:
            candidates = frappe.get_all("Journal Entry", filters={"company": self.company, "cheque_no": self.name, "voucher_type": "Bank Entry"}, fields=["name", "user_remark"], limit_page_length=0)
            marker = "POS bank commission and VAT posting | Posting: {0}".format(self.name)
            generated = [row.name for row in candidates if cstr(row.user_remark).strip().startswith(marker)]
            if len(generated) > 1:
                frappe.throw("More than one generated Journal Entry was found for this POS Accounting Posting.")
            if generated:
                journal_entry_name = generated[0]
        if not journal_entry_name or not frappe.db.exists("Journal Entry", journal_entry_name):
            return
        if frappe.db.exists(self.doctype, self.name):
            frappe.db.set_value(self.doctype, self.name, "journal_entry", None, update_modified=False)
        journal_entry = frappe.get_doc("Journal Entry", journal_entry_name)
        if cint(journal_entry.docstatus) == 1:
            journal_entry.cancel()
        if frappe.db.exists("Journal Entry", journal_entry_name):
            frappe.delete_doc("Journal Entry", journal_entry_name, ignore_permissions=True, force=True)
