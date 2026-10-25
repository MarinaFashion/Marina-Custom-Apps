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
    ("masked_card_number", ("pan", "masked_pan", "masked_card_number")),
    ("terminal_id", ("tid", "terminal_id", "device_terminal_id")),
    ("auth_code", ("auth_code", "authorization_code")),
    ("transaction_time", ("transaction_time",)),
)


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _safe_masked_pan(value):
    """Preserve safe PAN layout without inventing card digits or card length.

    Alhamrani's native "pan" is Masked PAN. Keep the actual visible
    leading digits (at most six) and trailing four digits; convert ordinary
    mask glyphs to "*" for consistent ERP display. Separator characters
    are presentation only. Never copy a clear-text PAN or any exposed
    middle digits.
    """
    raw = cstr(value).strip()
    if not raw or len(raw) > 64:
        return ""
    if not re.fullmatch(r"[0-9*Xx#•●\s-]+", raw):
        return ""
    normalized = re.sub(r"[Xx#•●]", "*", re.sub(r"[\s-]", "", raw))
    if re.fullmatch(r"\d{4}", normalized):
        # Last-four-only reference. Length of the physical PAN is unknown.
        # Do not manufacture a presumed 15/16-digit PAN layout.
        return "****" + normalized

    match = re.fullmatch(r"(\d{0,6})(\*+)(\d{4})", normalized)
    if not match:
        return ""
    # Re-use the actual mask length given by the bank, without altering
    # significant digits or inventing an unsupported BIN/PAN length.
    return normalized



def _eligible_changes_with_reasons(meta, source, bank, previously_enriched=None):
    """Decide what to fill, with safe explanations for skipped fields.

    Diagnostic reasons never expose card numbers, auth codes, or other source
    values. Only the audited changes contain copied masked values.
    """
    previous = set(previously_enriched or ())
    changes, skipped = [], []
    for bank_field, source_candidates in FIELD_MAPPING:
        target = next((name for name in source_candidates if meta.has_field(name)), None)
        if not target:
            skipped.append({"field": bank_field, "reason": "Alhamrani target field unavailable"})
            continue
        if not _is_blank(source.get(target)):
            skipped.append({
                "field": bank_field,
                "reason": (
                    "Already enriched by this Manual Link"
                    if target in previous else "Alhamrani field already populated"
                ),
            })
            continue
        value = bank.get(bank_field)
        if _is_blank(value):
            skipped.append({"field": bank_field, "reason": "Bank POS value missing"})
            continue
        if bank_field == "masked_card_number":
            value = _safe_masked_pan(value)
            if not value:
                skipped.append({
                    "field": bank_field,
                    "reason": "Bank value is not a safely masked card reference",
                })
                continue
        df = meta.get_field(target)
        if df and df.fieldtype == "Select" and df.options:
            allowed = {line.strip() for line in cstr(df.options).splitlines() if line.strip()}
            if allowed and cstr(value).strip() not in allowed:
                skipped.append({"field": bank_field, "reason": "Value not allowed by Alhamrani field options"})
                continue
        if bank_field == "terminal_id":
            bank_profile = resolve_pos_profile(value, bank.transaction_date)
            source_profile = source.get("pos_profile")
            if source_profile and bank_profile and source_profile != bank_profile:
                skipped.append({"field": bank_field, "reason": "Bank terminal POS Profile differs"})
                continue
        if bank_field == "transaction_time":
            value = cstr(value).strip()
        changes.append({
            "bank_field": bank_field,
            "source_field": target,
            "original_value": source.get(target),
            "enriched_value": value,
        })
    return changes, skipped


def _eligible_changes(meta, source, bank):
    """Backwards-compatible helper for existing callers and tests."""
    return _eligible_changes_with_reasons(meta, source, bank)[0]



def apply_enrichment(link, bank):
    """Apply only after source pairing has been approved and audited.

    Called in the same database transaction as Manual Link creation. A failure
    rolls back both creation and enrichment. Locks prevent concurrent edits to
    the source row between validation, audit capture, and write.
    """
    if cstr(getattr(frappe.local, "site", "")) != "marinademo.frappe.cloud":
        # Never break the approved-link workflow on another site simply
        # because Demo-only enrichment is intentionally disabled there.
        link.db_set("enrichment_status", "Disabled", update_modified=False)
        return {"status": "Disabled", "fields": []}

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

    existing_audit = {}
    if cstr(link.get("enrichment_details")).strip():
        try:
            existing_audit = json.loads(link.get("enrichment_details"))
        except (TypeError, ValueError, AttributeError):
            frappe.throw(_("Existing enrichment audit is invalid. No changes were made."))
        if not isinstance(existing_audit, dict) or (
            existing_audit.get("bank_pos_transaction") != bank.name
            or existing_audit.get("alhamrani_transaction") != link.alhamrani_transaction
        ):
            frappe.throw(_("Previous enrichment audit belongs to different transactions."))
    previous_changes = existing_audit.get("changes") or []
    if not isinstance(previous_changes, list):
        frappe.throw(_("Existing enrichment change history is invalid."))
    prior_fields = {item.get("source_field") for item in previous_changes if isinstance(item, dict)}

    meta = frappe.get_meta(ALHAMRANI_DOCTYPE)
    changes, skipped = _eligible_changes_with_reasons(meta, source, bank, prior_fields)
    if any(item["source_field"] in prior_fields for item in changes):
        frappe.throw(_("Enrichment change history conflicts with current source fields."))

    # Keep ALL original changes to support rollback after subsequent retries.
    audit = {
        "source": "Bank POS Transaction",
        "bank_pos_transaction": bank.name,
        "alhamrani_transaction": link.alhamrani_transaction,
        "response_meaning": source.get("response_meaning"),
        "changes": previous_changes + changes,
        "skipped": skipped,
        "attempts": int(existing_audit.get("attempts") or 0) + 1,
    }
    if changes:
        updates = {entry["source_field"]: entry["enriched_value"] for entry in changes}
        frappe.db.set_value(
            ALHAMRANI_DOCTYPE, link.alhamrani_transaction, updates,
            update_modified=True,
        )
    status = "Applied" if audit["changes"] else "No Eligible Fields"
    link.db_set({
        "enrichment_status": status,
        "enrichment_details": json.dumps(audit, ensure_ascii=False, default=cstr),
        "enriched_by": frappe.session.user,
        "enriched_on": now_datetime(),
    }, update_modified=False)
    return {
        "status": status,
        "fields": [entry["source_field"] for entry in changes],
        "skipped": skipped,
    }


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
