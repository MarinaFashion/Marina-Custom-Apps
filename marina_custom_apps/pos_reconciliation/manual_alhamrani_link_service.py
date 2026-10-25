"""Controlled one-to-one manual pairing of approved Alhamrani and Bank POS transactions.

Demo: audited enrichment of empty Alhamrani fields is permitted after approval.
Original JSON terminal evidence, settlements and accounting remain unchanged.
"""
import re

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime
from marina_custom_apps.pos_reconciliation.alhamrani_adapter import AlhamraniAdapter, ALHAMRANI_DOCTYPE
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile
from marina_custom_apps.pos_reconciliation.manual_alhamrani_enrichment import apply_enrichment

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
def find_manual_link_candidates(alhamrani_name):
    """Offer only evidenced candidates; the user must explicitly approve a link."""
    _require_approver()
    if not frappe.db.exists(ALHAMRANI_DOCTYPE, alhamrani_name):
        frappe.throw(_("Alhamrani transaction does not exist."))
    adapter = AlhamraniAdapter()
    source = frappe.get_doc(ALHAMRANI_DOCTYPE, alhamrani_name).as_dict()
    if not adapter.is_approved(source):
        frappe.throw(_("Alhamrani transaction is not approved."))
    alh = adapter.normalized_row(source)
    alh.pos_profile = resolve_pos_profile(alh.terminal_id, alh.transaction_date) or alh.source_pos_profile
    rrn = cstr(alh.rrn).strip()
    if not re.fullmatch(r"\d{12}", rrn) or not alh.transaction_date or not alh.pos_profile:
        return []
    banks = frappe.get_all("Bank POS Transaction", filters={
        "rrn": rrn,
        "transaction_date": alh.transaction_date,
        "pos_profile": alh.pos_profile,
        "transaction_status": ["in", ["Approved", "APPROVED", "approved"]],
    }, fields=["name", "rrn", "transaction_date", "transaction_amount", "transaction_type",
               "transaction_status", "pos_profile", "terminal_id", "transaction_time"], limit_page_length=100)
    # Keep the preview aligned with the existing reconciliation time tolerance.
    configured_tolerance = frappe.db.get_single_value(
        "POS Reconciliation Settings", "transaction_time_tolerance_seconds"
    )
    time_tolerance = max(0, min(int(60 if configured_tolerance is None else configured_tolerance), 300))
    time_origin = (
        "transaction" if alh.comparison_transaction_time
        else "responded_at" if adapter.fields.get("responded_at") and source.get(adapter.fields["responded_at"])
        else "sent_at" if adapter.fields.get("sent_at") and source.get(adapter.fields["sent_at"])
        else "creation"
    )
    results = []
    for bank in banks:
        if frappe.db.exists(LINK, {"bank_pos_transaction": bank.name}):
            continue
        try:
            validate_manual_pair(bank, alh)
        except frappe.ValidationError:
            continue
        # Read-only evidence for the user's final mapping confirmation.
        # A source Device Map is not equivalent to a bank Terminal ID and must
        # never be described as an automatically verified device match.
        results.append({
            "name": bank.name,
            "amount": bank.transaction_amount,
            "date": cstr(bank.transaction_date),
            "time": cstr(bank.transaction_time).strip(),
            "time_tolerance_seconds": time_tolerance,
            "pos_profile": bank.pos_profile,
            "rrn": rrn,
            "bank_terminal_id": cstr(bank.terminal_id).strip(),
            "alhamrani": {
                "name": alhamrani_name,
                "pos_profile": alh.pos_profile,
                "amount": alh.amount,
                "date": cstr(alh.transaction_date),
                "time": cstr(alh.transaction_time).strip(),
                "time_origin": time_origin,
            },
        })
    return results


@frappe.whitelist()
def approve_manual_link(alhamrani_name, bank_pos_name, reason):
    _require_approver()
    alhamrani_name, bank_pos_name = cstr(alhamrani_name).strip(), cstr(bank_pos_name).strip()
    reason = cstr(reason).strip()
    if not reason or len(reason) < 10:
        frappe.throw(_("Provide a reason of at least 10 characters."))
    # Serialize competing approvals for the same source or bank record.
    frappe.db.sql("SELECT name FROM `tabBank POS Transaction` WHERE name=%s FOR UPDATE", (bank_pos_name,))
    frappe.db.sql("SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE", (alhamrani_name,))
    if frappe.db.exists(LINK, {"alhamrani_transaction": alhamrani_name}) or frappe.db.exists(LINK, {"bank_pos_transaction": bank_pos_name}):
        frappe.throw(_("One of these transactions already has a manual link."))
    bank = frappe.db.get_value("Bank POS Transaction", bank_pos_name,
        ["name", "rrn", "pos_profile", "transaction_date", "transaction_time",
         "transaction_amount", "transaction_status", "transaction_type",
         "card_type", "masked_card_number", "terminal_id", "auth_code"], as_dict=True)
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
    existing_bank = frappe.db.get_value("POS Reconciliation Record",
        {"bank_transaction": bank_pos_name}, ["name", "alhamrani_transaction"], as_dict=True)
    if existing_bank and existing_bank.alhamrani_transaction and existing_bank.alhamrani_transaction != alhamrani_name:
        frappe.throw(_("Bank POS transaction is already paired with another Alhamrani record: {0}.").format(existing_bank.name))
    existing_alh = frappe.db.get_value("POS Reconciliation Record",
        {"alhamrani_transaction": alhamrani_name}, ["name", "bank_transaction"], as_dict=True)
    if existing_alh and existing_alh.bank_transaction and existing_alh.bank_transaction != bank_pos_name:
        frappe.throw(_("Alhamrani transaction is already paired with another Bank POS record: {0}.").format(existing_alh.name))
    # Source rows are not mutated; the reconciliation engine consumes only approved links.
    doc = frappe.get_doc({"doctype": LINK, "alhamrani_transaction": alhamrani_name,
        "bank_pos_transaction": bank_pos_name, "rrn": cstr(bank.rrn).strip(),
        "amount": flt(bank.transaction_amount, 2), "pos_profile": bank.pos_profile,
        "status": "Approved", "reason": reason,
        "approved_by": frappe.session.user, "approved_on": now_datetime()})
    doc.insert(ignore_permissions=True)
    # Same Frappe request/DB transaction: an enrichment error rolls back link
    # creation too. Never commit here and never fabricate response_json.
    enrichment = apply_enrichment(doc, bank)
    return {"link": doc.name, "status": "Approved",
            "enrichment": enrichment}


@frappe.whitelist()
def enrich_existing_manual_link(link_name):
    """Opt-in Demo backfill for previously approved links, without relinking.

    Revalidate the original evidence and never change accounting/settlements.
    Earlier links already have a valid one-to-one pairing: this action only
    populates empty external Alhamrani fields with an audit snapshot.
    """
    _require_approver()
    link_name = cstr(link_name).strip()
    frappe.db.sql(
        "SELECT name FROM `tabManual Alhamrani POS Link` WHERE name=%s FOR UPDATE",
        (link_name,),
    )
    link = frappe.get_doc(LINK, link_name)
    if link.status != "Approved":
        frappe.throw(_("Only approved manual links can be enriched."))
    frappe.db.sql(
        "SELECT name FROM `tabBank POS Transaction` WHERE name=%s FOR UPDATE",
        (link.bank_pos_transaction,),
    )
    frappe.db.sql(
        "SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE",
        (link.alhamrani_transaction,),
    )
    fields = [
        "name", "rrn", "pos_profile", "transaction_date", "transaction_time",
        "transaction_amount", "transaction_status", "transaction_type",
        "card_type", "masked_card_number", "terminal_id", "auth_code",
    ]
    bank = frappe.db.get_value(
        "Bank POS Transaction", link.bank_pos_transaction, fields, as_dict=True
    )
    if not bank:
        frappe.throw(_("Linked Bank POS transaction no longer exists."))
    adapter = AlhamraniAdapter()
    source = frappe.get_doc(ALHAMRANI_DOCTYPE, link.alhamrani_transaction).as_dict()
    alh = adapter.normalized_row(source)
    if not adapter.is_approved(source):
        frappe.throw(_("Alhamrani source approval is no longer valid."))
    alh.pos_profile = resolve_pos_profile(alh.terminal_id, alh.transaction_date) or alh.source_pos_profile
    validate_manual_pair(bank, alh)
    result = apply_enrichment(link, bank)
    return {"link": link.name, "status": link.status, "enrichment": result}


@frappe.whitelist()
def unlink_manual_link(link_name, reason):
    """Controlled Demo unlink retaining the approval and original source history.

    All mutations occur in the current Frappe request transaction. A failure
    before commit rolls back BOTH source-field restoration and status change.
    The stable BANK| reconciliation identity and all bank settlement/statement
    data remain untouched. A subsequent reconciliation run detaches the
    Alhamrani source and refreshes the settlement-aware match classification.
    """
    _require_approver()
    if cstr(getattr(frappe.local, "site", "")) != "marinademo.frappe.cloud":
        frappe.throw(_("Controlled Unlink is available on Demo only until Finance acceptance."))

    link_name = cstr(link_name).strip()
    reason = cstr(reason).strip()
    if len(reason) < 10 or len(reason) > 2000:
        frappe.throw(_("Provide an unlink reason between 10 and 2000 characters."))

    # Serialize concurrent Unlink and Enrich Remaining Fields operations.
    frappe.db.sql(
        "SELECT name FROM `tabManual Alhamrani POS Link` WHERE name=%s FOR UPDATE",
        (link_name,),
    )
    link = frappe.get_doc(LINK, link_name)
    if link.status != "Approved":
        frappe.throw(_("This manual link is not Approved; it may already be unlinked."))

    bank_name = cstr(link.bank_pos_transaction).strip()
    alhamrani_name = cstr(link.alhamrani_transaction).strip()
    if not bank_name or not alhamrani_name:
        frappe.throw(_("Approved link has incomplete source references. Unlink is blocked."))

    from marina_custom_apps.pos_reconciliation.doctype.manual_alhamrani_pos_link.manual_alhamrani_pos_link import (
        _assert_no_financial_dependencies,
    )
    from marina_custom_apps.pos_reconciliation.manual_alhamrani_enrichment import (
        rollback_enrichment,
    )

    # Also locks the source bank and Alhamrani rows to prevent concurrent
    # approval or pairing changes; ensures no commission/VAT accounting
    # posting or unsafe settlement references before altering any source.
    _assert_no_financial_dependencies(bank_name, alhamrani_name)

    # Do not keep copied bank data attached to an unlinked slip: restore ONLY
    # original values that the current manual link actually enriched.
    rollback_enrichment(link)

    # The original approved document stays as a read-only historical record.
    # The active source fields are cleared to release their SQL UNIQUE slots
    # (MySQL/MariaDB accepts multiple NULL values in unique indexes), so a
    # future approved link can use the same source after reconciliation.
    # All previous approvals, reasons and enrichment evidence remain intact.
    frappe.db.set_value(
        LINK,
        link_name,
        {
            "status": "Revoked",
            "original_bank_pos_transaction": bank_name,
            "original_alhamrani_transaction": alhamrani_name,
            "bank_pos_transaction": None,
            "alhamrani_transaction": None,
            "unlink_reason": reason,
            "unlinked_by": frappe.session.user,
            "unlinked_on": now_datetime(),
        },
        update_modified=True,
    )
    return {
        "link": link_name,
        "status": "Revoked",
        "bank_pos_transaction": bank_name,
        "alhamrani_transaction": alhamrani_name,
        "requires_reconciliation": True,
    }
