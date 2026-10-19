"""Release general bank reconciliation matches when a Journal Entry is cancelled/deleted.

Reconciliation records are not accounting postings. The entire affected matching
group must be released: some groups contain other payment/Journal Entry lines.
The bank-side Link must be cleared before deletion to avoid circular links.
All operations participate in the invoking Journal Entry DB transaction.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from marina_custom_apps.pos_reconciliation.accounting_service import (
    on_journal_entry_cancel as existing_pos_on_cancel,
    on_journal_entry_trash as existing_pos_on_trash,
)

MATCH = "Bank Statement Reconciliation Match"
MATCH_GL = "Bank Statement Reconciliation GL Row"
BANK = "Marina Bank Statement Transaction"


def release_matches_for_journal_entry(journal_name):
    """Idempotently release every entire reconciliation group involving this JE."""
    matches = frappe.get_all(
        MATCH_GL,
        filters={
            "parenttype": MATCH,
            "parentfield": "gl_rows",
            "voucher_type": "Journal Entry",
            "voucher_no": journal_name,
        },
        pluck="parent",
        limit_page_length=0,
    )
    count = 0
    for match_name in sorted(set(matches)):
        if not frappe.db.exists(MATCH, match_name):
            continue
        # Serialize competing cancellation/reconciliation operations.
        frappe.db.sql(
            "SELECT name FROM `tabBank Statement Reconciliation Match` WHERE name = %s FOR UPDATE",
            (match_name,),
        )
        match = frappe.get_doc(MATCH, match_name)
        bank_names = list(dict.fromkeys(
            row.statement_transaction for row in match.get("bank_rows", [])
            if row.statement_transaction
        ))
        for name in sorted(bank_names):
            frappe.db.sql(
                "SELECT name FROM `tabMarina Bank Statement Transaction` WHERE name = %s FOR UPDATE",
                (name,),
            )
            if not frappe.db.exists(BANK, name):
                frappe.throw(_("Bank transaction {0} is missing; cannot release match {1}.").format(name, match_name))
            row = frappe.db.get_value(
                BANK, name,
                ["bank_statement_reconciliation_match", "reconciliation_status", "debit", "credit"],
                as_dict=True,
            )
            if row.bank_statement_reconciliation_match != match_name:
                frappe.throw(
                    _("Bank transaction {0} no longer points to reconciliation match {1}. Refresh and resolve manually.").format(
                        name, match_name
                    )
                )
            if row.reconciliation_status != "Reconciled":
                frappe.throw(_("Bank transaction {0} is not Reconciled; cleanup stopped.").format(name))
            amount = abs(flt(row.credit) - flt(row.debit))
            frappe.db.set_value(
                BANK, name,
                {
                    "reconciliation_status": "Unreconciled",
                    "allocated_amount": 0,
                    "remaining_amount": amount,
                    "bank_statement_reconciliation_match": None,
                    "transaction_category": None,
                    "reconciled_on": None,
                    "reconciled_by": None,
                },
                update_modified=False,
            )
            # Keep an immutable-style user-visible historical note even when
            # the original JE and matching document are later deleted.
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": BANK,
                "reference_name": name,
                "content": (
                    "Bank reconciliation released on Journal Entry cancellation/deletion. "
                    "Journal Entry: {0}; removed Match: {1}; by: {2}; at: {3}."
                ).format(journal_name, match_name, frappe.session.user, now_datetime()),
            }).insert(ignore_permissions=True)
        # All incoming Bank transaction links are now cleared. Removing the Match
        # also deletes its Bank and GL child rows, releasing references to the JE.
        frappe.delete_doc(MATCH, match_name, ignore_permissions=True)
        count += 1
    return count


def on_cancel(doc, method=None):
    # Preserve every existing Marina POS Journal Entry protection and state update.
    existing_pos_on_cancel(doc, method)
    release_matches_for_journal_entry(doc.name)


def on_trash(doc, method=None):
    # Handles cancelled legacy Journal Entries that still have stale matching links.
    existing_pos_on_trash(doc, method)
    release_matches_for_journal_entry(doc.name)
