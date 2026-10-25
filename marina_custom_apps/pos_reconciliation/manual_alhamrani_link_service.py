"""Controlled one-to-one manual pairing of approved Alhamrani and Bank POS transactions.

Never edits source payment transactions, accounting postings, or settlements.
"""
import re

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime
from marina_custom_apps.pos_reconciliation.alhamrani_adapter import AlhamraniAdapter, ALHAMRANI_DOCTYPE
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


def validate_manual_pair(bank, alh):
    """Validate source evidence both during approval and during reconciliation reruns."""
    rrn = cstr(bank.rrn).strip()
    if not re.fullmatch(r"\d{12}", rrn) or rrn != cstr(alh.rrn).strip():
        frappe.throw(_("Invalid or mismatched manual-link RRN."))
    if alh.amount is None or abs(flt(bank.transaction_amount, 2) - flt(alh.amount, 2)) > 0.01:
        frappe.throw(_("Manual link payment amounts differ."))
    if not bank.transaction_date or not alh.transaction_date or getdate(bank.transaction_date) != getdate(alh.transaction_date):
        frappe.throw(_("Manual link dates differ."))
    if not bank.pos_profile or not alh.pos_profile or bank.pos_profile != alh.pos_profile:
        frappe.throw(_("Manual link POS Profiles differ."))
    bank_type = cstr(bank.transaction_type).strip().upper()
    source_type = cstr(alh.transaction_type).strip().upper()
    if bank_type not in {"PURCHASE", "REFUND"} or (source_type and source_type != bank_type):
        frappe.throw(_("Manual link transaction types differ."))
    if cstr(bank.transaction_status).strip().upper() != "APPROVED":
        frappe.throw(_("Bank POS transaction is not approved."))
    if cstr(alh.status).strip().upper() not in {"APPROVED", "SUCCESS", "COMPLETED"}:
        frappe.throw(_("Alhamrani transaction is not approved."))


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
    if not frappe.db.exists(ALHAMRANI_DOCTYPE, alhamrani_name):
        frappe.throw(_("Alhamrani transaction does not exist."))
    source = frappe.get_doc(ALHAMRANI_DOCTYPE, alhamrani_name).as_dict()
    alh = adapter.normalized_row(source)
    if not adapter.is_approved(source):
        frappe.throw(_("Alhamrani transaction is not approved."))
    alh.pos_profile = resolve_pos_profile(alh.terminal_id, alh.transaction_date) or alh.source_pos_profile
    validate_manual_pair(bank, alh)
    # Source rows are not mutated; the reconciliation engine consumes only approved links.
    doc = frappe.get_doc({"doctype": LINK, "alhamrani_transaction": alhamrani_name,
        "bank_pos_transaction": bank_pos_name, "rrn": cstr(bank.rrn).strip(),
        "amount": flt(bank.transaction_amount, 2), "pos_profile": bank.pos_profile,
        "status": "Approved", "reason": reason,
        "approved_by": frappe.session.user, "approved_on": now_datetime()})
    doc.insert(ignore_permissions=True)
    return {"link": doc.name, "status": "Approved"}
