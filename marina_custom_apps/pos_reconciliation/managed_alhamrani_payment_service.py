"""Guided, audited AUP correction/approval and POS Bank manual linking.

Preview is read-only. Apply rechecks the exact candidate under row locks and
uses the existing services in one Frappe request transaction (no commits).
"""
import re

import frappe
from frappe import _
from frappe.utils import cstr

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    ALHAMRANI_DOCTYPE, AlhamraniAdapter,
)
from marina_custom_apps.pos_reconciliation.manual_alhamrani_control_service import (
    _read, _check_unlinked, _decide_action, _is_manual,
    _rrn, _reason, _site_guard,
    update_alhamrani_control,
)
from marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service import (
    LINK, validate_manual_pair, approve_manual_link,
)
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

BANK_FIELDS = [
    "name", "rrn", "transaction_date", "transaction_time",
    "transaction_amount", "transaction_type", "transaction_status",
    "pos_profile", "terminal_id",
]


def _related_records(name):
    linked = frappe.db.get_value(
        LINK, {"alhamrani_transaction": name},
        ["name", "status", "bank_pos_transaction"], as_dict=True,
    ) if frappe.db.exists("DocType", LINK) else None
    record = frappe.db.get_value(
        "POS Reconciliation Record", {"alhamrani_transaction": name},
        ["name", "bank_transaction", "match_status", "accounting_status"],
        as_dict=True,
    ) if frappe.db.exists("DocType", "POS Reconciliation Record") else None
    return linked, record


def _source(name):
    doc, invoice = _read(name)
    adapter = AlhamraniAdapter()
    source = adapter.normalized_row(doc.as_dict())
    source.pos_profile = (
        resolve_pos_profile(source.terminal_id, source.transaction_date)
        or source.source_pos_profile
    )
    return doc, invoice, adapter, source


def _candidates(source, rrn):
    """Indexed RRN+date lookup; validate every candidate before exposing it."""
    if not rrn or not source.transaction_date or source.amount is None:
        return []
    rows = frappe.get_all(
        "Bank POS Transaction",
        filters={
            "rrn": rrn,
            "transaction_date": source.transaction_date,
            "transaction_status": ["in", ["Approved", "APPROVED", "approved"]],
        },
        fields=BANK_FIELDS,
        limit_page_length=50,
    )
    if not rows:
        return []
    names = [bank.name for bank in rows]
    # Batch membership and protection checks: no per-candidate database queries.
    linked_banks = {
        row.bank_pos_transaction for row in frappe.get_all(
            LINK, filters={"bank_pos_transaction": ["in", names]},
            fields=["bank_pos_transaction"], limit_page_length=0,
        )
    }
    existing_by_bank = {
        row.bank_transaction: row for row in frappe.get_all(
            "POS Reconciliation Record",
            filters={"bank_transaction": ["in", names]},
            fields=["bank_transaction", "alhamrani_transaction", "accounting_status",
                    "accounting_posting", "journal_entry"],
            limit_page_length=0,
        )
    }
    tolerance = frappe.db.get_single_value(
        "POS Reconciliation Settings", "transaction_time_tolerance_seconds"
    )
    tolerance = max(0, min(int(60 if tolerance is None else tolerance), 300))
    found = []
    for bank in rows:
        if bank.name in linked_banks:
            continue
        existing = existing_by_bank.get(bank.name)
        if existing and (
            (existing.alhamrani_transaction and existing.alhamrani_transaction != source.name)
            or existing.accounting_posting or existing.journal_entry
            or cstr(existing.accounting_status) in {
                "Posted", "Draft Created", "Posted - Review Required", "Draft - Review Required"
            }
        ):
            continue
        try:
            validate_manual_pair(bank, source)
        except (frappe.ValidationError, frappe.PermissionError):
            continue
        found.append({
            "name": bank.name,
            "rrn": rrn,
            "amount": bank.transaction_amount,
            "date": cstr(bank.transaction_date),
            "time": cstr(bank.transaction_time).strip(),
            "pos_profile": bank.pos_profile,
            "bank_terminal_id": cstr(bank.terminal_id),
            "time_tolerance_seconds": tolerance,
            "alhamrani": {
                "name": source.name,
                "pos_profile": source.pos_profile,
                "amount": source.amount,
                "date": cstr(source.transaction_date),
                "time": cstr(source.transaction_time).strip(),
                "time_origin": "transaction" if source.comparison_transaction_time else "creation",
            },
        })
    return found


def _preview(name, proposed_rrn=None):
    doc, invoice, adapter, source = _source(name)
    linked, record = _related_records(doc.name)
    existing_rrn = cstr(source.rrn).strip()
    candidate_rrn = cstr(proposed_rrn).strip() or existing_rrn
    if proposed_rrn and candidate_rrn != existing_rrn:
        _rrn(candidate_rrn)

    if linked:
        state = "already_linked"
    elif record and record.bank_transaction:
        state = "already_matched"
    else:
        _check_unlinked(doc)
        approved = cstr(doc.get("status")).strip().upper() in {"APPROVED", "SUCCESS", "COMPLETED"}
        if _is_manual(doc):
            state = "needs_rrn_correction" if (
                candidate_rrn != existing_rrn or not re.fullmatch(r"\d{12}", existing_rrn)
            ) else "ready_to_link"
        elif approved:
            # Existing approved electronic payments can be investigated and
            # manually linked, but must never be manually re-confirmed or edited.
            state = "ready_to_link" if re.fullmatch(r"\d{12}", existing_rrn) and candidate_rrn == existing_rrn else "investigate"
        else:
            action = _decide_action(doc)  # rejects conflicting electronic evidence
            state = "needs_confirmation" if action == "confirm" else "investigate"

    # Never auto-approve or silently rewrite an electronic response.
    if state == "needs_rrn_correction" and not _is_manual(doc):
        frappe.throw(_("Only a previously manually confirmed AUP may have its RRN corrected."))
    valid_for_search = bool(re.fullmatch(r"\d{12}", candidate_rrn))
    candidates = []
    if state not in {"already_linked", "already_matched", "investigate"} and valid_for_search:
        source.rrn = candidate_rrn
        if state == "needs_confirmation":
            source.status = "Approved"  # preview only; the stored AUP is untouched
        candidates = _candidates(source, candidate_rrn)

    return {
        "name": doc.name,
        "sales_invoice": invoice,
        "status": cstr(doc.get("status")),
        "response_meaning": cstr(doc.get("response_meaning")),
        "rrn": existing_rrn,
        "proposed_rrn": candidate_rrn if proposed_rrn else "",
        "amount": source.amount,
        "date": cstr(source.transaction_date),
        "pos_profile": source.pos_profile,
        "state": state,
        "existing_link": dict(linked) if linked else None,
        "existing_record": dict(record) if record else None,
        "candidates": candidates,
        "requires_slip": state in {"needs_confirmation", "needs_rrn_correction"},
    }


@frappe.whitelist()
def preview_managed_alhamrani_payment(alhamrani_name, proposed_rrn=None):
    _site_guard()
    return _preview(alhamrani_name, proposed_rrn)


@frappe.whitelist()
def apply_managed_alhamrani_payment(
    alhamrani_name, rrn=None, bank_pos_name=None, reason=None,
    confirmed=0, confirm_mapping=0, expected_state=None,
):
    _site_guard()
    if cstr(confirmed).lower() not in {"1", "true"}:
        frappe.throw(_("Confirm that you reviewed the transaction evidence."))
    reason = _reason(reason)
    bank_pos_name = cstr(bank_pos_name).strip()
    proposed_rrn = cstr(rrn).strip()
    if bank_pos_name:
        # Lock order matches the existing link service: Bank POS, then AUP.
        frappe.db.sql(
            "SELECT name FROM `tabBank POS Transaction` WHERE name=%s FOR UPDATE",
            (bank_pos_name,),
        )
    frappe.db.sql(
        "SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE",
        (cstr(alhamrani_name).strip(),),
    )
    preview = _preview(alhamrani_name, proposed_rrn or None)
    state = preview["state"]
    if expected_state and cstr(expected_state) != state:
        frappe.throw(_("Payment state changed since preview. Refresh the proposal."))
    if state in {"already_linked", "already_matched", "investigate"}:
        frappe.throw(_("This AUP is already linked, reconciled, or requires investigation; changes are blocked."))

    current_rrn = cstr(preview["rrn"]).strip()
    rrn_to_use = _rrn(proposed_rrn or current_rrn)
    needs_update = state == "needs_confirmation" or rrn_to_use != current_rrn
    if state == "needs_rrn_correction" and not needs_update:
        frappe.throw(_("Enter a corrected 12-digit RRN."))
    if bank_pos_name:
        if cstr(confirm_mapping).lower() not in {"1", "true"}:
            frappe.throw(_("Explicit Bank POS mapping confirmation is required."))
        allowed = {row["name"] for row in preview["candidates"]}
        if bank_pos_name not in allowed:
            frappe.throw(_("The selected Bank POS is no longer an eligible match."))
    elif not needs_update:
        frappe.throw(_("No change requested: select an eligible Bank POS transaction."))

    update_result = None
    if needs_update:
        update_result = update_alhamrani_control(
            alhamrani_name, rrn_to_use, reason, confirmed=1,
            expected_action="confirm" if state == "needs_confirmation" else "correct_rrn",
        )
    link_result = None
    if bank_pos_name:
        # Same request transaction: if link or enrichment fails, the AUP
        # correction and its audit Comment roll back as well.
        link_result = approve_manual_link(alhamrani_name, bank_pos_name, reason)

    return {
        "name": alhamrani_name,
        "updated": bool(update_result),
        "linked": bool(link_result),
        "bank_pos_transaction": bank_pos_name or None,
        "link": link_result.get("link") if link_result else None,
        "requires_reconciliation": True,
    }
