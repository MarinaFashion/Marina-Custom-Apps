"""Controlled reversal of general Bank Statement Reconciliation Match groups."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

MATCH = "Bank Statement Reconciliation Match"
BANK = "Marina Bank Statement Transaction"


def release_match(match_name, reason, origin):
    """Clear bank links, retain history and delete the full match atomically."""
    if not frappe.db.exists(MATCH, match_name):
        frappe.throw(_("Reconciliation match {0} no longer exists.").format(match_name))
    frappe.db.sql(
        "SELECT name FROM `tabBank Statement Reconciliation Match` WHERE name=%s FOR UPDATE",
        (match_name,),
    )
    doc = frappe.get_doc(MATCH, match_name)
    bank_names = sorted(set(
        row.statement_transaction for row in doc.get("bank_rows", [])
        if row.statement_transaction
    ))
    if not bank_names or not doc.get("gl_rows"):
        frappe.throw(_("The match has missing Bank or GL rows and cannot be reversed automatically."))

    for name in bank_names:
        frappe.db.sql(
            "SELECT name FROM `tabMarina Bank Statement Transaction` WHERE name=%s FOR UPDATE",
            (name,),
        )
        row = frappe.db.get_value(
            BANK, name,
            ["bank_statement_reconciliation_match", "reconciliation_status", "debit", "credit"],
            as_dict=True,
        )
        if not row or row.bank_statement_reconciliation_match != match_name or row.reconciliation_status != "Reconciled":
            frappe.throw(_("Bank transaction {0} has changed; refresh before reversing this match.").format(name))
        amount = abs(flt(row.credit) - flt(row.debit))
        frappe.db.set_value(BANK, name, {
            "reconciliation_status": "Unreconciled",
            "allocated_amount": 0,
            "remaining_amount": amount,
            "bank_statement_reconciliation_match": None,
            "transaction_category": None,
            "reconciled_on": None,
            "reconciled_by": None,
        }, update_modified=False)
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": BANK,
            "reference_name": name,
            "content": (
                "Reconciliation match {0} reversed. Source: {1}. Reason: {2}. "
                "By: {3}. On: {4}. Bank rows: {5}; GL rows: {6}."
            ).format(match_name, origin, reason, frappe.session.user, now_datetime(),
                     ", ".join(bank_names), ", ".join(row.gl_entry for row in doc.gl_rows)),
        }).insert(ignore_permissions=True)

    # Protect direct deletion without obstructing controlled JE cancellation.
    previous = getattr(frappe.flags, "allow_bank_reconciliation_match_delete", False)
    try:
        frappe.flags.allow_bank_reconciliation_match_delete = True
        frappe.delete_doc(MATCH, match_name, ignore_permissions=True)
    finally:
        frappe.flags.allow_bank_reconciliation_match_delete = previous

    return {"released_bank_rows": len(bank_names), "released_gl_rows": len(doc.gl_rows)}


@frappe.whitelist()
def reverse_match(match_name, reason):
    if not frappe.has_permission("Bank Statement Reconciliation", "write"):
        frappe.throw(_("Write permission on Bank Statement Reconciliation is required."), frappe.PermissionError)
    if not frappe.has_permission(MATCH, "read"):
        frappe.throw(_("Read permission on the reconciliation match is required."), frappe.PermissionError)
    reason = cstr(reason).strip()
    if len(reason) < 5:
        frappe.throw(_("Enter a reversal reason of at least five characters."))
    if len(reason) > 500:
        frappe.throw(_("Reversal reason cannot exceed 500 characters."))
    result = release_match(match_name, reason, "Manual reversal")
    return result
