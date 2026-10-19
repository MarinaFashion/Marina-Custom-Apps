from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

DOCTYPE = "Bank Reconciliation Exclusion"
BANK_TRANSACTION = "Marina Bank Statement Transaction"
GL_MATCH_ROW = "Bank Statement Reconciliation GL Row"
MATCH_DOCTYPE = "Bank Statement Reconciliation Match"
REASONS = {
    "POS / Sales Transaction",
    "Duplicate Transaction",
    "Historical Transaction",
    "Out of Reconciliation Scope",
    "Other",
}


def _assert_manager():
    """Authorization comes from ERPNext DocType Write permissions."""
    if not frappe.has_permission("Bank Statement Reconciliation", "write"):
        frappe.throw(_("Write access to Bank Statement Reconciliation is required."), frappe.PermissionError)
    if not frappe.has_permission(DOCTYPE, "write"):
        frappe.throw(_("Write access to Bank Reconciliation Exclusion is required."), frappe.PermissionError)


def _source_key(source_type, record_name):
    return hashlib.sha256(f"{source_type}:{record_name}".encode("utf-8")).hexdigest()


def _bank_gl_account(bank_account):
    account = frappe.db.get_value("Bank Account", bank_account, "account")
    if not account:
        frappe.throw(_("Bank Account is not linked to an ERPNext GL Account."))
    return account


def active_excluded_names(bank_account, source_type):
    """Read only active exclusions for one bank and side of the workbench."""
    if not frappe.db.exists("DocType", DOCTYPE):
        return set()
    return set(frappe.get_all(
        DOCTYPE,
        filters={"bank_account": bank_account, "source_type": source_type, "status": "Excluded"},
        pluck="source_record",
        limit_page_length=0,
    ))


def _source_details(bank_account, source_type, record_name):
    if source_type == "Bank Statement":
        source = frappe.db.get_value(
            BANK_TRANSACTION, record_name,
            ["bank_account", "processing_date", "reference_number", "debit", "credit",
             "is_pos_statement_line", "reconciliation_status", "bank_statement_reconciliation_match"],
            as_dict=True,
        )
        if not source or source.bank_account != bank_account or source.is_pos_statement_line:
            frappe.throw(_("This is not an eligible non-POS bank statement transaction for the selected account."))
        if source.reconciliation_status != "Unreconciled" or source.bank_statement_reconciliation_match:
            frappe.throw(_("Already reconciled bank transactions cannot be excluded."))
        return {
            "source_doctype": BANK_TRANSACTION,
            "transaction_date": source.processing_date,
            "reference_number": cstr(source.reference_number).strip(),
            "amount": flt(flt(source.credit, 2) - flt(source.debit, 2), 2),
        }

    if source_type == "GL Entry":
        source = frappe.db.get_value(
            "GL Entry", record_name,
            ["account", "posting_date", "voucher_type", "voucher_no", "debit", "credit", "is_cancelled"],
            as_dict=True,
        )
        if not source or source.account != _bank_gl_account(bank_account):
            frappe.throw(_("GL Entry is not for the selected bank GL Account."))
        if source.is_cancelled or source.voucher_type not in ("Payment Entry", "Journal Entry"):
            frappe.throw(_("Only active bank Payment Entry or Journal Entry GL lines can be excluded."))
        if frappe.db.exists(GL_MATCH_ROW, {"gl_entry": record_name, "parenttype": MATCH_DOCTYPE}):
            frappe.throw(_("Already reconciled GL Entries cannot be excluded."))
        if source.voucher_type == "Journal Entry" and frappe.db.exists(
            "POS Accounting Posting", {"journal_entry": source.voucher_no}
        ):
            frappe.throw(_("POS-generated Journal Entries are already outside this reconciliation."))
        reference_field = "reference_no" if source.voucher_type == "Payment Entry" else "cheque_no"
        return {
            "source_doctype": "GL Entry",
            "transaction_date": source.posting_date,
            "reference_number": cstr(frappe.db.get_value(source.voucher_type, source.voucher_no, reference_field)).strip(),
            "amount": flt(flt(source.debit, 2) - flt(source.credit, 2), 2),
        }
    frappe.throw(_("Invalid exclusion source type."))


def exclude_transaction(bank_account, source_type, record_name, reason, comments=None):
    _assert_manager()
    bank_account = cstr(bank_account).strip()
    source_type = cstr(source_type).strip()
    record_name = cstr(record_name).strip()
    reason = cstr(reason).strip()
    if not bank_account or not record_name or reason not in REASONS:
        frappe.throw(_("Bank Account, transaction, and a valid exclusion reason are required."))

    # Lock the source GL/bank row so concurrent exclusion requests cannot race.
    if source_type == "Bank Statement":
        frappe.db.sql("SELECT name FROM `tabMarina Bank Statement Transaction` WHERE name = %s FOR UPDATE", (record_name,))
    elif source_type == "GL Entry":
        frappe.db.sql("SELECT name FROM `tabGL Entry` WHERE name = %s FOR UPDATE", (record_name,))
    else:
        frappe.throw(_("Invalid exclusion source type."))

    info = _source_details(bank_account, source_type, record_name)
    key = _source_key(source_type, record_name)
    existing = frappe.db.get_value(DOCTYPE, {"source_key": key}, "name")
    if existing:
        doc = frappe.get_doc(DOCTYPE, existing)
        if doc.status == "Excluded":
            frappe.throw(_("This transaction is already excluded."))
        if doc.bank_account != bank_account:
            frappe.throw(_("Exclusion is associated with another Bank Account."))
    else:
        doc = frappe.new_doc(DOCTYPE)
        doc.source_key = key
        doc.source_type = source_type
        doc.source_record = record_name
        doc.source_doctype = info["source_doctype"]
        doc.bank_account = bank_account

    now = now_datetime()
    doc.status = "Excluded"
    doc.transaction_date = info["transaction_date"]
    doc.amount = info["amount"]
    doc.reference_number = info["reference_number"]
    doc.exclusion_reason = reason
    doc.comments = cstr(comments or "").strip()[:1000]
    doc.excluded_by = frappe.session.user
    doc.excluded_on = now
    doc.restored_by = None
    doc.restored_on = None
    doc.restore_reason = None
    doc.append("history", {
        "action": "Excluded",
        "action_by": frappe.session.user,
        "action_on": now,
        "reason": reason,
        "comments": doc.comments,
    })
    doc.flags.allow_exclusion_change = True
    if existing:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return {"name": doc.name, "status": doc.status}


def restore_exclusion(exclusion_name, reason):
    _assert_manager()
    reason = cstr(reason).strip()
    if not reason:
        frappe.throw(_("Restoration reason is required."))
    if len(reason) > 1000:
        frappe.throw(_("Restoration reason must be within 1000 characters."))

    doc = frappe.get_doc(DOCTYPE, cstr(exclusion_name).strip())
    # Serialize restoration against an exclusion of the same transaction.
    source_table = "tabMarina Bank Statement Transaction" if doc.source_type == "Bank Statement" else "tabGL Entry"
    frappe.db.sql(f"SELECT name FROM `{source_table}` WHERE name = %s FOR UPDATE", (doc.source_record,))
    doc.reload()
    if doc.status != "Excluded":
        frappe.throw(_("Transaction is not currently excluded."))

    now = now_datetime()
    doc.status = "Restored"
    doc.restored_by = frappe.session.user
    doc.restored_on = now
    doc.restore_reason = reason
    doc.append("history", {
        "action": "Restored",
        "action_by": frappe.session.user,
        "action_on": now,
        "reason": "Restored",
        "comments": reason,
    })
    doc.flags.allow_exclusion_change = True
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "status": doc.status}
