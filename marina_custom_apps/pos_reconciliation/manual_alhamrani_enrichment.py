"""Audited Demo-only enrichment of Alhamrani slip payments from Bank POS.

Original terminal/request payloads remain unchanged. Only empty source fields
are populated; changes are recorded in the Manual Alhamrani POS Link itself.
A guarded unlink restores ONLY values this module wrote, and only when they
have not changed independently. Do not deploy to Live without acceptance.
"""
import json
import re

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    ALHAMRANI_DOCTYPE, is_manual_slip_confirmation,
)
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

# Strict allow-list. Never copy financial amounts, original timestamps, RRN,
# approval status, request_json or response_json.
FIELD_MAPPING = (
    ("card_type", ("card_type",)),
    ("masked_card_number", ("masked_pan", "masked_card_number")),
    ("terminal_id", ("tid", "terminal_id", "device_terminal_id")),
    ("auth_code", ("auth_code", "authorization_code")),
    ("transaction_time", ("transaction_time",)),
)


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _safe_masked_pan(value):
    """Never store a full PAN, even if an import accidentally contains one."""
    value = cstr(value).strip()
    if not value:
        return ""
    digits = sum(ch.isdigit() for ch in value)
    masked = any(ch in "*Xx•" for ch in value)
    if digits > 10 or (not masked and digits > 4):
        return ""
    if not re.fullmatch(r"[0-9*Xx•\s-]+", value):
        return ""
    return value


def _eligible_changes(meta, source, bank):
    """Produce the narrowly scoped before/after audit for genuinely empty fields."""
    changes = []
    for bank_field, source_candidates in FIELD_MAPPING:
        target = next((name for name in source_candidates if meta.has_field(name)), None)
        if not target or not _is_blank(source.get(target)):
            continue
        value = bank.get(bank_field)
        if _is_blank(value):
            continue
        if bank_field == "masked_card_number":
            value = _safe_masked_pan(value)
            if not value:
                continue
        if bank_field == "terminal_id":
            # Never change the POS Profile implied by the original transaction.
            bank_profile = resolve_pos_profile(value, bank.transaction_date)
            source_profile = source.get("pos_profile")
            if source_profile and bank_profile and source_profile != bank_profile:
                continue
        if bank_field == "transaction_time":
            # A transaction clock must not overwrite POS send/response timestamps.
            # Only a separate optional source field is eligible.
            value = cstr(value).strip()
        changes.append({
            "bank_field": bank_field,
            "source_field": target,
            "original_value": source.get(target),
            "enriched_value": value,
        })
    return changes


def apply_enrichment(link, bank):
    """Apply only after source pairing has been approved and audited.

    Called in the same database transaction as Manual Link creation. A failure
    rolls back both creation and enrichment. Locks prevent concurrent edits to
    the source row between validation, audit capture, and write.
    """
    if cstr(getattr(frappe.local, "site", "")) != "marinademo.frappe.cloud":
        frappe.throw(_("Bank-to-Alhamrani enrichment is enabled on Demo only."))

    frappe.db.sql(
        "SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE",
        (link.alhamrani_transaction,),
    )
    source_doc = frappe.get_doc(ALHAMRANI_DOCTYPE, link.alhamrani_transaction)
    source = source_doc.as_dict()
    if not is_manual_slip_confirmation(source.get("response_meaning")):
        # Do not rewrite legitimate electronic terminal response records.
        link.db_set("enrichment_status", "Not Applicable", update_modified=False)
        return {"status": "Not Applicable", "fields": []}

    meta = frappe.get_meta(ALHAMRANI_DOCTYPE)
    changes = _eligible_changes(meta, source, bank)
    # Persist provenance even when no eligible field was available.
    audit = {
        "source": "Bank POS Transaction",
        "bank_pos_transaction": bank.name,
        "alhamrani_transaction": link.alhamrani_transaction,
        "response_meaning": source.get("response_meaning"),
        "changes": changes,
    }
    if changes:
        updates = {entry["source_field"]: entry["enriched_value"] for entry in changes}
        frappe.db.set_value(
            ALHAMRANI_DOCTYPE, link.alhamrani_transaction, updates,
            update_modified=True,
        )
    link.db_set({
        "enrichment_status": "Applied" if changes else "No Eligible Fields",
        "enrichment_details": json.dumps(audit, ensure_ascii=False, default=cstr),
        "enriched_by": frappe.session.user,
        "enriched_on": now_datetime(),
    }, update_modified=False)
    return {"status": "Applied" if changes else "No Eligible Fields",
            "fields": [entry["source_field"] for entry in changes]}


def rollback_enrichment(link):
    """Undo exclusively the fields written by this link; fail on any conflict.

    This is called from the guarded Demo Delete hook only AFTER checking
    accounting and settlement dependencies. The caller's delete transaction
    atomically rolls back these changes if the document delete fails.
    """
    details = cstr(link.get("enrichment_details")).strip()
    if not details:
        return
    try:
        audit = json.loads(details)
        changes = audit.get("changes") or []
    except (TypeError, ValueError, AttributeError):
        frappe.throw(_("Invalid enrichment audit. Unlinking is blocked."))

    if (audit.get("bank_pos_transaction") != link.bank_pos_transaction
            or audit.get("alhamrani_transaction") != link.alhamrani_transaction):
        frappe.throw(_("Enrichment audit does not match the current link."))

    if not changes:
        return

    meta = frappe.get_meta(ALHAMRANI_DOCTYPE)
    allowlist = {target for _, candidates in FIELD_MAPPING for target in candidates}
    names = [entry.get("source_field") for entry in changes]
    if len(set(names)) != len(names) or any(
        name not in allowlist or not meta.has_field(name) for name in names
    ):
        frappe.throw(_("Enrichment audit fields are invalid. Unlinking is blocked."))

    frappe.db.sql(
        "SELECT name FROM `tabAlhamrani Transaction` WHERE name=%s FOR UPDATE",
        (link.alhamrani_transaction,),
    )
    current = frappe.db.get_value(
        ALHAMRANI_DOCTYPE, link.alhamrani_transaction, names, as_dict=True
    )
    if not current:
        frappe.throw(_("Alhamrani source record is missing. Unlinking is blocked."))

    restored = {}
    for entry in changes:
        field = entry["source_field"]
        if cstr(current.get(field)) != cstr(entry.get("enriched_value")):
            frappe.throw(_(
                "Alhamrani field {0} changed after enrichment. "
                "Do not unlink until Finance reviews the discrepancy."
            ).format(field))
        restored[field] = entry.get("original_value")

    frappe.db.set_value(
        ALHAMRANI_DOCTYPE, link.alhamrani_transaction, restored,
        update_modified=True,
    )
