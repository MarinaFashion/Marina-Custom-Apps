"""Carry a bank-reference Journal Entry Account row ID into its GL Entry.

ERPNext v15 sets GL Entry.voucher_detail_no from Journal Entry Account.reference_detail_no,
not from the Journal Entry Account row name. Its GL merge key includes this field,
so distinct bank-referenced lines are not merged together.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from marina_custom_apps.pos_reconciliation.accounting_service import (
    validate_generated_journal_entry_before_submit,
)


def before_submit(doc, method=None):
    # Preserve the existing posting controls for POS-generated Journal Entries.
    validate_generated_journal_entry_before_submit(doc, method)

    if not frappe.get_meta("Journal Entry Account").has_field("custom_bank_reference_number"):
        return

    for row in doc.get("accounts", []):
        reference = cstr(row.get("custom_bank_reference_number")).strip()
        if not reference:
            continue
        if row.get("reference_type") or row.get("reference_name"):
            frappe.throw(
                _("Row {0}: Bank Reference Number requires an accounting line without a linked document.").format(
                    row.idx
                )
            )
        if not row.name:
            frappe.throw(
                _("Row {0}: Save the Journal Entry before submitting line-level bank references.").format(
                    row.idx
                )
            )
        if row.get("reference_detail_no") and row.reference_detail_no != row.name:
            frappe.throw(
                _("Row {0}: Cannot override an existing Reference Detail No.").format(row.idx)
            )
        # Only unlinked rows with a bank reference receive this stable internal
        # reference. Other lines keep their standard ERPNext reference semantics.
        row.reference_detail_no = row.name
