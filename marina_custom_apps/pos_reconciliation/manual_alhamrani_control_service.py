"""Controlled terminal-slip confirmation and correction of manually entered Alhamrani RRNs.

Never alter financial amounts, terminal JSON or response codes. No background
reconciliation or accounting posting is performed by these actions.
"""
import re

import frappe
from frappe import _
from frappe.utils import cstr

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    ALHAMRANI_DOCTYPE, MANUAL_SLIP_RESPONSE_MEANING,
)
from marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service import _require_approver

ALLOWED_SITES = {"marinademo.frappe.cloud", "marina.frappe.cloud"}


def _site_guard():
    _require_approver()
    if cstr(getattr(frappe.local, "site", "")) not in ALLOWED_SITES:
        frappe.throw(_("This action is restricted to approved Marina sites."))


def _invoice_field():
    meta = frappe.get_meta(ALHAMRANI_DOCTYPE)
    # Fail closed rather than accidentally approving an AUP without invoice evidence.
    if not meta.has_field("sales_invoice"):
        frappe.throw(_("Alhamrani Sales Invoice field is unavailable. Contact the administrator."))
    return "sales_invoice"


def _read(name, lock=False):
    name = cstr(name).strip()
    if not re.fullmatch(r"AUP-\d{4}-\d{5}(?:-\d+)?", name):
        frappe.throw(_("Enter a valid Alhamrani transaction ID."))
    if lock:
        frappe.db.sql("SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE", (name,))
    if not frappe.db.exists(ALHAMRANI_DOCTYPE, name):
        frappe.throw(_("Alhamrani transaction not found."))
    doc = frappe.get_doc(ALHAMRANI_DOCTYPE, name)
    invoice_field = _invoice_field()
    invoice = cstr(doc.get(invoice_field)).strip()
    if not invoice:
        frappe.throw(_("Sales Invoice number must be recorded before confirming a payment or correcting its RRN."))
    return doc, invoice


def _check_unlinked(doc):
    """Do not mutate a source already consumed by matching or financial workflows."""
    name = doc.name
    if frappe.db.exists("DocType", "Manual Alhamrani POS Link") and frappe.db.exists(
        "Manual Alhamrani POS Link", {"alhamrani_transaction": name}
    ):
        frappe.throw(_("AUP already has a Manual Alhamrani POS Link. Finance must review it before changes."))
    if frappe.db.exists("DocType", "POS Reconciliation Record"):
        rows = frappe.get_all(
            "POS Reconciliation Record",
            filters={"alhamrani_transaction": name},
            fields=["name", "bank_transaction", "accounting_status", "accounting_posting",
                    "journal_entry", "settlement_number", "bank_statement_reconciliation",
                    "bank_statement_settlement"],
            limit_page_length=2,
        )
        for row in rows:
            # An unlinked, Alhamrani-only preview is safe to refresh on the next
            # reconciliation run. Never mutate an already paired or financially
            # consumed source, even if its status label is stale.
            financial_fields = (
                "bank_transaction", "accounting_posting", "journal_entry",
                "settlement_number", "bank_statement_reconciliation",
                "bank_statement_settlement",
            )
            if any(cstr(row.get(field)).strip() for field in financial_fields):
                frappe.throw(_("AUP is linked to reconciliation or financial evidence. Finance review is required."))
            if cstr(row.get("accounting_status")).strip() in {
                "Draft Created", "Posted", "Draft - Review Required", "Posted - Review Required"
            }:
                frappe.throw(_("AUP has protected accounting status. Source correction is blocked."))


def _rrn(value):
    value = cstr(value).strip()
    if not re.fullmatch(r"\d{12}", value):
        frappe.throw(_("RRN must contain exactly 12 digits."))
    return value


def _reason(value):
    value = cstr(value).strip()
    if len(value) < 10 or len(value) > 500:
        frappe.throw(_("Provide a confirmation or correction reason of 10 to 500 characters."))
    return value


def _is_manual(doc):
    return " ".join(cstr(doc.get("response_meaning")).split()).casefold() == MANUAL_SLIP_RESPONSE_MEANING.casefold()


def _decide_action(doc):
    """Choose workflow from current evidence; never trust a UI-supplied mode."""
    if _is_manual(doc):
        return "correct_rrn"
    if cstr(doc.get("status")).strip().upper() in {"APPROVED", "SUCCESS", "COMPLETED"}:
        frappe.throw(_("An approved electronic transaction cannot be manually re-confirmed."))
    if cstr(doc.get("response_code")).strip():
        frappe.throw(_("An electronic response code exists; manual confirmation is blocked."))
    if cstr(doc.get("response_meaning")).strip():
        frappe.throw(_("Existing electronic response meaning is present. Manual confirmation is blocked."))
    return "confirm"


def _audit(doc, label, old, new, reason):
    # Same request transaction as the source update; a failed audit prevents change.
    lines = [label, "User: " + frappe.session.user, "Reason: " + reason]
    for fieldname in sorted(new):
        lines.append("{}: {!r} -> {!r}".format(fieldname, old.get(fieldname), new[fieldname]))
    frappe.get_doc({
        "doctype": "Comment", "comment_type": "Info",
        "reference_doctype": ALHAMRANI_DOCTYPE,
        "reference_name": doc.name,
        "content": "\n".join(lines),
    }).insert(ignore_permissions=True)


@frappe.whitelist()
def preview_alhamrani_control(alhamrani_name):
    _site_guard()
    doc, invoice = _read(alhamrani_name)
    _check_unlinked(doc)
    action = _decide_action(doc)
    return {
        "action": action,
        "name": doc.name, "sales_invoice": invoice,
        "rrn": cstr(doc.get("rrn")).strip(),
        "status": cstr(doc.get("status")).strip(),
        "response_meaning": cstr(doc.get("response_meaning")).strip(),
        "response_code_present": bool(cstr(doc.get("response_code")).strip()),
        "pos_profile": cstr(doc.get("pos_profile")).strip(),
    }


@frappe.whitelist()
def update_alhamrani_control(alhamrani_name, rrn, reason, confirmed=0, expected_action=None):
    _site_guard()
    if cstr(confirmed).lower() not in {"1", "true"}:
        frappe.throw(_("Terminal-slip verification acknowledgement is mandatory."))
    new_rrn = _rrn(rrn)
    reason = _reason(reason)
    doc, invoice = _read(alhamrani_name, lock=True)
    _check_unlinked(doc)
    action = _decide_action(doc)
    if expected_action and cstr(expected_action) != action:
        frappe.throw(_("Transaction state changed after preview. Reload and review again."))
    old = {
        "rrn": doc.get("rrn"),
        "response_meaning": doc.get("response_meaning"),
        "status": doc.get("status"),
    }
    if action == "confirm":
        if cstr(doc.get("status")).strip().upper() in {"APPROVED", "SUCCESS", "COMPLETED"}:
            frappe.throw(_("This transaction is already approved; do not reconfirm it."))
        if cstr(doc.get("response_code")).strip():
            frappe.throw(_("An electronic response code exists; terminal-slip override is blocked."))
        # Unconfirmed manual entries may contain a mistyped RRN. Keep the
        # original value in the audit; financial/link guards run first.
        if cstr(doc.get("response_meaning")).strip() and not _is_manual(doc):
            frappe.throw(_("Existing electronic response meaning is present. Manual override is blocked."))
        updates = {
            "rrn": new_rrn,
            "response_meaning": MANUAL_SLIP_RESPONSE_MEANING,
            "status": "Approved",
        }
    else:
        # _decide_action has already established manual confirmation.
        if not cstr(doc.get("rrn")).strip():
            frappe.throw(_("Existing RRN is empty; use manual confirmation instead."))
        if cstr(doc.get("rrn")).strip() == new_rrn:
            frappe.throw(_("New RRN must differ from current RRN."))
        updates = {"rrn": new_rrn}

    _audit(doc, "Controlled Alhamrani " + action, old, updates, reason)
    frappe.db.set_value(ALHAMRANI_DOCTYPE, doc.name, updates, update_modified=True)
    return {"name": doc.name, "action": action, "invoice": invoice, "updated_fields": list(updates)}
