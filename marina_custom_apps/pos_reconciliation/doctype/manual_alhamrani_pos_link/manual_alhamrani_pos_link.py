"""Demo-only guarded unlink of approved Alhamrani/Bank POS transactions.

Bank settlement and bank statement records remain unchanged. The Bank POS
reconciliation identity survives; the Alhamrani source is separated by a rerun.
Any commission/VAT accounting posting or Journal Entry blocks unlink.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

PROTECTED_ACCOUNTING_STATUSES = {
    "Draft Created", "Posted", "Draft - Review Required", "Posted - Review Required"
}


def _has_text(value):
    return bool(cstr(value).strip())


def _is_accounting_protected(row):
    """Settlement alone is not accounting evidence of commission/VAT posting."""
    return (
        _has_text(row.get("accounting_posting"))
        or _has_text(row.get("journal_entry"))
        or cstr(row.get("accounting_status")).strip() in PROTECTED_ACCOUNTING_STATUSES
    )


def _assert_no_financial_dependencies(bank_name, alhamrani_name):
    """Permit a bank-settled manual link to be deleted ONLY without posting evidence.

    Settlement, statement rows and existing bank reconciliation identities are
    preserved; the reconciliation rerun can safely update the existing BANK|row
    and create a separate ALHAMRANI|row. Never remove financial source rows.
    All checks are limited to a single indexed bank/Alhamrani source.
    """
    # Serialize against other approval/unlink actions and refuse active runs.
    from marina_custom_apps.pos_reconciliation.period_control import assert_bank_transactions_open
    assert_bank_transactions_open([bank_name])
    frappe.db.sql(
        "SELECT name FROM `tabBank POS Transaction` WHERE name=%s FOR UPDATE",
        (bank_name,),
    )
    frappe.db.sql(
        "SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE",
        (alhamrani_name,),
    )

    bank = frappe.db.get_value(
        "Bank POS Transaction", bank_name,
        ["transaction_date", "settled", "settlement_number",
         "pos_reconciliation_number", "accounting_status", "accounting_posting",
         "journal_entry"], as_dict=True
    )
    if not bank:
        frappe.throw(_("Bank POS transaction is missing. Finance review is required."))
    if _is_accounting_protected(bank):
        frappe.throw(_(
            "This Bank POS transaction contributes to a commission/VAT "
            "accounting posting or Journal Entry. Unlink is blocked."
        ))

    # Even if header accounting fields are stale, posting child evidence wins.
    if frappe.db.exists("POS Accounting Posting Item", {"bank_transaction": bank_name}):
        frappe.throw(_(
            "This Bank POS transaction is referenced by a commission/VAT "
            "POS Accounting Posting Item. Unlink is blocked until Finance resolves it."
        ))

    results = {}
    for field, name in (
        ("bank_transaction", bank_name),
        ("alhamrani_transaction", alhamrani_name),
    ):
        rows = frappe.get_all(
            "POS Reconciliation Record",
            filters={field: name},
            fields=[
                "name", "record_key", "bank_transaction", "alhamrani_transaction",
                "transaction_date", "accounting_status", "accounting_posting",
                "journal_entry", "settlement_number", "settlement_date",
                "pos_reconciliation_number", "bank_statement_status",
                "bank_statement_reconciliation", "bank_statement_settlement",
                "bank_statement_references",
            ],
            limit_page_length=25,
        )
        if len(rows) == 25:
            frappe.throw(_("Too many reconciliation results found. Finance review is required."))
        for row in rows:
            results[row.name] = row

    bank_record = None
    for row in results.values():
        # Don't detach a source paired to an unrelated transaction.
        if (
            row.bank_transaction and row.bank_transaction != bank_name
            or row.alhamrani_transaction and row.alhamrani_transaction != alhamrani_name
        ):
            frappe.throw(_(
                "Reconciliation result {0} points to another payment source. Unlink is blocked."
            ).format(row.name))
        if _is_accounting_protected(row):
            frappe.throw(_(
                "Reconciliation result {0} contains commission/VAT posting evidence. "
                "Unlink is blocked."
            ).format(row.name))
        if row.bank_transaction:
            # Same record key and name survive the rerun, protecting any
            # settled statement/settlement-child references.
            if row.record_key != "BANK|" + bank_name:
                frappe.throw(_(
                    "Reconciliation result {0} has an unexpected identity. Unlink is blocked."
                ).format(row.name))
            if bank_record and bank_record != row.name:
                frappe.throw(_("Duplicate bank reconciliation results found. Unlink is blocked."))
            bank_record = row.name
        elif (
            _has_text(row.bank_statement_settlement)
            or _has_text(row.bank_statement_reconciliation)
            or _has_text(row.bank_statement_references)
            or _has_text(row.settlement_number)
        ):
            frappe.throw(_(
                "Alhamrani-only reconciliation result {0} has financial references. "
                "Unlink is blocked."
            ).format(row.name))

        if frappe.db.exists("POS Accounting Posting Item", {"reconciliation_record": row.name}):
            frappe.throw(_(
                "Reconciliation result {0} is referenced by a commission/VAT "
                "accounting item. Unlink is blocked."
            ).format(row.name))

    # A settled bank has an underlying settlement source: leave it intact.
    # Its child may reference only the stable BANK| record, never an
    # Alhamrani-only or other reconciliation row that reruns could remove.
    settlement_rows = frappe.get_all(
        "POS Bank Settlement Transaction",
        filters={"bank_pos_transaction": bank_name},
        fields=["name", "reconciliation_record"],
        limit_page_length=25,
    )
    if len(settlement_rows) == 25:
        frappe.throw(_("Too many bank settlement references found. Finance review is required."))
    for child in settlement_rows:
        if child.reconciliation_record and child.reconciliation_record != bank_record:
            frappe.throw(_(
                "Bank settlement transaction {0} refers to an unstable reconciliation "
                "result. Unlink is blocked to preserve settlement history."
            ).format(child.name))

    # If settlement metadata exists but we don't have a BANK| result yet,
    # there is no guarantee which record downstream references will target.
    if not bank_record and (
        bank.settled or _has_text(bank.settlement_number)
        or _has_text(bank.pos_reconciliation_number) or settlement_rows
    ):
        frappe.throw(_(
            "This settled Bank POS transaction has no stable reconciliation "
            "record. Run reconciliation before attempting to unlink."
        ))


class ManualAlhamraniPOSLink(Document):
    def validate(self):
        # Source identifiers remain mandatory for APPROVED links. They become
        # NULL only after a controlled unlink, releasing the database's two
        # unique constraints without deleting the historical document.
        if self.status == "Approved" and (
            not _has_text(self.bank_pos_transaction)
            or not _has_text(self.alhamrani_transaction)
        ):
            frappe.throw(_("Approved manual links require both source transactions."))

    def on_trash(self):
        # Never delete audit documents. Revoked links remain as immutable
        # history and their original sources are stored separately.
        frappe.throw(_(
            "Manual POS links cannot be deleted. Use Actions > Unlink Transactions "
            "to safely revoke an approved link and retain its history."
        ))
