"""Controlled one-to-one manual pairing of approved Alhamrani and Bank POS transactions.

Never edits source payment transactions, accounting postings, or settlements.
"""
import re

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime
from marina_custom_apps.pos_reconciliation.alhamrani_adapter import AlhamraniAdapter
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

LINK = "Manual Alhamrani POS Link"


def _require_approver():
    if not (set(frappe.get_roles()) & {"Accounts Manager", "System Manager"}):
        frappe.throw(_("Accounts Manager or System Manager role is required."), frappe.PermissionError)


def active_manual_links():
    """Return approved persistent links; a single indexed query per run."""
    if not frappe.db.exists("DocType", LINK):
        return {}
    rows = frappe.get_all(LINK, filters={"status": "Approved"},
                          fields=["name", "bank_pos_transaction", "alhamrani_transaction"],
                          limit_page_length=0)
    return {row.bank_pos_transaction: row.alhamrani_transaction for row in rows}


@frappe.whitelist()
def approve_manual_link(alhamrani_name, bank_pos_name, reason):
    _require_approver()
    alhamrani_name, bank_pos_name = cstr(alhamrani_name).strip(), cstr(bank_pos_name).strip()
    reason = cstr(reason).strip()
    if not reason or len(reason) < 10:
        frappe.throw(_("Provide a reason of at least 10 characters."))
    if frappe.db.exists(LINK, {"alhamrani_transaction": alhamrani_name}) or frappe.db.exists(LINK, {"bank_pos_transaction": bank_pos_name}):
        frappe.throw(_("One of these transactions already has a manual link."))
    bank = frappe.db.get_value("Bank POS Transaction", bank_pos_name,
        ["name", "rrn", "pos_profile", "transaction_date", "transaction_amount", "transaction_status", "transaction_type"], as_dict=True)
    if not bank or cstr(bank.transaction_status).upper() != "APPROVED":
        frappe.throw(_("Bank POS transaction is missing or not approved."))
    adapter = AlhamraniAdapter()
    alh_doc = frappe.db.get_value(adapter.doctype, alhamrani_name, ["name"], as_dict=True)
    if not alh_doc:
        frappe.throw(_("Alhamrani transaction does not exist."))
    alh = adapter.normalized_row(frappe.get_doc(adapter.doctype, alhamrani_name).as_dict())
    if not adapter.is_approved(frappe.get_doc(adapter.doctype, alhamrani_name).as_dict()):
        frappe.throw(_("Alhamrani transaction is not approved."))
    if not re.fullmatch(r"\d{12}", cstr(bank.rrn).strip()) or cstr(bank.rrn).strip() != cstr(alh.rrn).strip():
        frappe.throw(_("A matching, valid 12-digit RRN is required."))
    if alh.amount is None or abs(flt(bank.transaction_amount, 2) - flt(alh.amount, 2)) > 0.01:
        frappe.throw(_("Payment amounts do not match."))
    if getdate(bank.transaction_date) != getdate(alh.transaction_date):
        frappe.throw(_("Dates do not match; investigate before linking."))
    resolved = resolve_pos_profile(alh.terminal_id, alh.transaction_date) or alh.source_pos_profile
    if not resolved or not bank.pos_profile or resolved != bank.pos_profile:
        frappe.throw(_("A matching verified POS Profile is required."))
    if cstr(alh.transaction_type).upper() != cstr(bank.transaction_type).upper():
        frappe.throw(_("Transaction types do not match."))
    # Source rows are not mutated; the reconciliation engine consumes only approved links.
    doc = frappe.get_doc({"doctype": LINK, "alhamrani_transaction": alhamrani_name,
        "bank_pos_transaction": bank_pos_name, "rrn": cstr(bank.rrn).strip(),
        "amount": flt(bank.transaction_amount, 2), "pos_profile": bank.pos_profile,
        "status": "Approved", "reason": reason,
        "approved_by": frappe.session.user, "approved_on": now_datetime()})
    doc.insert(ignore_permissions=True)
    return {"link": doc.name, "status": "Approved"}
