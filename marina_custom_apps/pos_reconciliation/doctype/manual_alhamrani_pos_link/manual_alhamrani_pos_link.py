"""Demo-only deletion guard for manually approved Alhamrani/Bank POS links.

Deleting the link is NOT an accounting reversal. Unprotected reconciliation
results are regenerated after a subsequent POS reconciliation run.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

PROTECTED_ACCOUNTING_STATUSES = {
    "Draft Created", "Posted", "Draft - Review Required", "Posted - Review Required"
}
PROTECTED_STATEMENT_STATUSES = {"Statement Found", "Fully Reconciled", "Exception"}


def _has_text(value):
    return bool(cstr(value).strip())


def _assert_no_financial_dependencies(bank_name, alhamrani_name):
    """Reject unlink where an existing matching result or bank has dependencies.

    Indexed lookups limited to one bank/source avoid scanning large POS tables.
    Do not delete, rewrite, or invalidate bank/GL/settlement records.
    """
    bank = frappe.db.get_value(
        "Bank POS Transaction", bank_name,
        ["transaction_date", "settled", "settlement_number", "pos_reconciliation_number",
         "accounting_status", "accounting_posting", "journal_entry"], as_dict=True
    )
    if not bank:
        frappe.throw(_("Bank POS transaction no longer exists; the link requires Finance review before removal."))

    # Also guards active reconciliation executions and closed financial periods.
    from marina_custom_apps.pos_reconciliation.period_control import assert_bank_transactions_open
    assert_bank_transactions_open([bank_name])

    if (
        bank.settled or _has_text(bank.settlement_number)
        or _has_text(bank.pos_reconciliation_number)
        or _has_text(bank.accounting_posting)
        or _has_text(bank.journal_entry)
        or cstr(bank.accounting_status) in PROTECTED_ACCOUNTING_STATUSES
    ):
        frappe.throw(_(
            "This Bank POS transaction has settlement or accounting evidence. "
            "The manual link cannot be deleted for testing; Finance must review it."
        ))

    # Check child financial references even where parent status is not populated.
    for child, field in (
        ("POS Bank Settlement Transaction", "bank_pos_transaction"),
        ("POS Accounting Posting Item", "bank_transaction"),
    ):
        if frappe.db.exists(child, {field: bank_name}):
            frappe.throw(_(
                "This Bank POS transaction is referenced by {0}; deleting the manual link is blocked."
            ).format(child))

    results = {}
    for field, name in (
        ("bank_transaction", bank_name),
        ("alhamrani_transaction", alhamrani_name),
    ):
        rows = frappe.get_all(
            "POS Reconciliation Record",
            filters={field: name},
            fields=[
                "name", "bank_transaction", "alhamrani_transaction",
                "transaction_date", "accounting_status", "accounting_posting",
                "journal_entry", "settlement_number", "settlement_date",
                "pos_reconciliation_number", "bank_statement_status",
                "bank_statement_reconciliation", "bank_statement_settlement",
                "bank_statement_references",
            ],
            limit_page_length=25,
        )
        if len(rows) == 25:
            frappe.throw(_("Too many reconciliation results found for this link. Finance review is required."))
        for row in rows:
            results[row.name] = row

    for row in results.values():
        # Don't detach unexpected source mappings through this temporary option.
        if (
            row.bank_transaction and row.bank_transaction != bank_name
            or row.alhamrani_transaction and row.alhamrani_transaction != alhamrani_name
        ):
            frappe.throw(_(
                "Reconciliation result {0} points to a different payment source; "
                "manual link deletion is blocked."
            ).format(row.name))

        if (
            _has_text(row.accounting_posting)
            or _has_text(row.journal_entry)
            or cstr(row.accounting_status) in PROTECTED_ACCOUNTING_STATUSES
            or _has_text(row.settlement_number)
            or row.settlement_date
            or _has_text(row.pos_reconciliation_number)
            or cstr(row.bank_statement_status) in PROTECTED_STATEMENT_STATUSES
            or _has_text(row.bank_statement_reconciliation)
            or _has_text(row.bank_statement_settlement)
            or _has_text(row.bank_statement_references)
        ):
            frappe.throw(_(
                "Reconciliation result {0} has settlement, bank statement, or "
                "accounting evidence. The manual link cannot be deleted."
            ).format(row.name))

        for child in ("POS Accounting Posting Item", "POS Bank Settlement Transaction"):
            if frappe.db.exists(child, {"reconciliation_record": row.name}):
                frappe.throw(_(
                    "Reconciliation result {0} is referenced by {1}. "
                    "The manual link cannot be deleted."
                ).format(row.name, child))


class ManualAlhamraniPOSLink(Document):
    def on_trash(self):
        # This is a temporary test-only capability, not a Live reversal feature.
        if cstr(getattr(frappe.local, "site", "")) != "marinademo.frappe.cloud":
            frappe.throw(_("Deleting approved manual POS links is permitted on Demo only."))
        if not (set(frappe.get_roles()) & {"Accounts Manager", "System Manager"}):
            frappe.throw(_("Accounts Manager or System Manager role is required."), frappe.PermissionError)
        _assert_no_financial_dependencies(
            cstr(self.bank_pos_transaction).strip(),
            cstr(self.alhamrani_transaction).strip(),
        )
        # Revert only bank-sourced values written by this approved link.
        # If any was subsequently edited, block deletion rather than
        # silently overwriting another actor's modification.
        from marina_custom_apps.pos_reconciliation.manual_alhamrani_enrichment import rollback_enrichment
        rollback_enrichment(self)
        # The link is removed by normal Frappe delete_doc. No reconciliation
        # or accounting rows are deleted here. Rerun reconciliation to split
        # the stale source pairing before attempting a different manual link.
        frappe.msgprint(_(
            "Manual link deletion passed financial checks. Once deleted, "
            "rerun POS Reconciliation for the same period to refresh both "
            "transactions to their unlinked results before linking again."
        ))
