from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.bank_reconciliation_exclusion_service import (
    exclude_transaction as exclude_bank_transaction,
    restore_exclusion as restore_bank_exclusion,
)

from marina_custom_apps.pos_reconciliation.bank_statement_gl_reconciliation_service import (
    get_workspace as get_reconciliation_workspace,
    save_matches as save_reconciliation_matches,
)


class BankStatementReconciliation(Document):
    pass


@frappe.whitelist()
def get_workspace(bank_account, tolerance=None, from_date=None, to_date=None, reference=None):
    if not frappe.has_permission("Bank Statement Reconciliation", "read"):
        frappe.throw(_("You are not permitted to view Bank Statement Reconciliation."), frappe.PermissionError)
    return get_reconciliation_workspace(bank_account, tolerance, from_date, to_date, reference)


@frappe.whitelist()
def save_matches(bank_account, matches, tolerance=None):
    if not frappe.has_permission("Bank Statement Reconciliation", "write"):
        frappe.throw(_("You are not permitted to save Bank Statement Reconciliation."), frappe.PermissionError)
    return save_reconciliation_matches(bank_account, matches, tolerance)


@frappe.whitelist()
def exclude_transaction(bank_account, source_type, record_name, reason, comments=None):
    return exclude_bank_transaction(bank_account, source_type, record_name, reason, comments)


@frappe.whitelist()
def restore_exclusion(exclusion_name, reason):
    return restore_bank_exclusion(exclusion_name, reason)
