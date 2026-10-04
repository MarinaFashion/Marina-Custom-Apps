from __future__ import annotations

import hashlib
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    ALHAMRANI_DOCTYPE,
    AlhamraniAdapter,
)
from marina_custom_apps.pos_reconciliation.card_type_mapping import (
    CardTypeMapper,
    get_card_type_mapper,
    normalize_card_type_token,
)
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

AMOUNT_TOLERANCE = 0.01

FINANCE_NOT_REQUIRED = "Not Required"
FINANCE_PENDING = "Pending Review"
FINANCE_APPROVED = "Checked & Approved"
FINANCE_INVESTIGATE = "Needs Investigation"

RECORD_UPDATE_FIELDS = (
    "transaction_date",
    "pos_profile",
    "terminal_id",
    "card_type",
    "bank_transaction",
    "alhamrani_doctype",
    "alhamrani_transaction",
    "match_status",
    "resolution_status",
    "before_integration",
    "discrepancy_fields",
    "alhamrani_duplicate_count",
    "settlement_number",
    "settlement_date",
    "pos_reconciliation_number",
    "bank_commission_amount",
    "bank_commission_vat_amount",
    "bank_settlement_amount",
    "bank_amount",
    "alhamrani_amount",
    "amount_difference",
    "bank_card_type",
    "alhamrani_card_type",
    "bank_masked_pan",
    "alhamrani_masked_pan",
    "alhamrani_emv_last4",
    "pan_validation_method",
    "bank_transaction_date",
    "alhamrani_transaction_date",
    "bank_transaction_time",
    "alhamrani_transaction_time",
    "finance_review_status",
    "finance_reviewed_by",
    "finance_reviewed_on",
    "finance_review_note",
    "manual_clearance_reason",
    "manual_cleared_by",
    "manual_cleared_on",
    "last_reconciled_on",
)


def normalize_card_type(value):
    """Generic formatting only; business aliases are configured in Settings."""
    return normalize_card_type_token(value)


def normalize_masked_pan(value):
    text = cstr(value).strip().upper().replace("X", "*")
    return "".join(ch for ch in text if ch.isdigit() or ch == "*")


def normalize_time(value):
    text = cstr(value).strip().split(".", 1)[0]
    if len(text) == 5 and text.count(":") == 1:
        text += ":00"
    return text


def _pan_last4(value):
    digits = "".join(ch for ch in cstr(value) if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else ""


def get_pan_validation_method(bank, alhamrani):
    """Validate PAN directly first, then fall back to ECR_EMVData last 4."""
    bank_pan = normalize_masked_pan(getattr(bank, "masked_card_number", None))
    alh_pan = normalize_masked_pan(getattr(alhamrani, "masked_pan", None))

    if bank_pan and alh_pan and bank_pan == alh_pan:
        return "Direct PAN"

    bank_last4 = _pan_last4(getattr(bank, "masked_card_number", None))
    emv_last4 = cstr(getattr(alhamrani, "emv_last4", None)).strip()
    if bank_last4 and emv_last4 and bank_last4 == emv_last4:
        return "EMV Last 4"

    if bank_pan and (alh_pan or emv_last4):
        return "Mismatch"

    return "Not Available"


def compare_transactions(bank, alhamrani, card_mapper=None):
    card_mapper = card_mapper or CardTypeMapper()
    discrepancies = []

    bank_amount = flt(bank.transaction_amount, 2)
    alh_amount = alhamrani.amount
    if alh_amount is None or abs(bank_amount - flt(alh_amount, 2)) > AMOUNT_TOLERANCE:
        discrepancies.append("Amount")

    bank_card = card_mapper.bank(bank.card_type)
    alh_card = card_mapper.alhamrani(alhamrani.card_type)
    if bank_card and alh_card and bank_card != alh_card:
        discrepancies.append("Card Type")

    if get_pan_validation_method(bank, alhamrani) == "Mismatch":
        discrepancies.append("Masked PAN")

    bank_date = getdate(bank.transaction_date) if bank.transaction_date else None
    alh_compare_date = getattr(alhamrani, "comparison_transaction_date", alhamrani.transaction_date)
    alh_date = getdate(alh_compare_date) if alh_compare_date else None
    if bank_date and alh_date and bank_date != alh_date:
        discrepancies.append("Transaction Date")

    bank_time = normalize_time(bank.transaction_time)
    alh_compare_time = getattr(alhamrani, "comparison_transaction_time", alhamrani.transaction_time)
    alh_time = normalize_time(alh_compare_time)
    if bank_time and alh_time and bank_time != alh_time:
        discrepancies.append("Transaction Time")

    return discrepancies


def _record_name(record_key):
    digest = hashlib.sha1(record_key.encode("utf-8")).hexdigest()[:20].upper()
    return f"PREC-{digest}"


def _record_key(run_name, bank_transaction=None, alhamrani_transaction=None):
    if bank_transaction:
        return f"{run_name}|BANK|{bank_transaction}"
    return f"{run_name}|ALHAMRANI|{alhamrani_transaction}"


def _bank_review_states():
    return {
        row.bank_transaction: row
        for row in frappe.get_all(
            "POS Bank Manual Clearance",
            fields=[
                "bank_transaction",
                "active",
                "reason",
                "cleared_by",
                "cleared_on",
                "finance_review_status",
                "finance_review_note",
                "finance_reviewed_by",
                "finance_reviewed_on",
            ],
            limit_page_length=0,
        )
        if row.bank_transaction
    }


def _integration_dates():
    return {
        cstr(row.terminal_id).strip(): getdate(row.integration_date)
        for row in frappe.get_all(
            "Terminal Reference",
            filters={"integration_date": ["is", "set"]},
            fields=["terminal_id", "integration_date"],
            limit_page_length=0,
        )
        if row.terminal_id and row.integration_date
    }


def _is_before_integration(bank, integration_dates):
    integration_date = integration_dates.get(cstr(bank.terminal_id).strip())
    if not integration_date or not bank.transaction_date:
        return 0
    return int(getdate(bank.transaction_date) < integration_date)


def _bank_rows(run, card_mapper):
    filters = {
        "transaction_date": ["between", [run.from_date, run.to_date]],
        "transaction_status": ["in", ["Approved", "APPROVED", "approved"]],
    }
    if run.pos_profile:
        filters["pos_profile"] = run.pos_profile

    rows = frappe.get_all(
        "Bank POS Transaction",
        filters=filters,
        fields=[
            "name",
            "reconciliation_key",
            "pos_profile",
            "terminal_id",
            "card_type",
            "masked_card_number",
            "transaction_date",
            "transaction_time",
            "transaction_amount",
            "settlement_number",
            "settlement_date",
            "pos_reconciliation_number",
            "fee_amount",
            "vat_amount",
            "settlement_amount",
        ],
        order_by="transaction_date asc, transaction_time asc, name asc",
        limit_page_length=0,
    )

    if run.card_type:
        wanted = card_mapper.resolve(run.card_type)
        rows = [row for row in rows if card_mapper.bank(row.card_type) == wanted]
    return rows


def _alhamrani_rows(run, card_mapper):
    adapter = AlhamraniAdapter()
    normalized = []
    wanted_card = card_mapper.resolve(run.card_type) if run.card_type else None

    for raw in adapter.get_rows(run.from_date, run.to_date):
        if not adapter.is_approved(raw):
            continue
        row = adapter.normalized_row(raw)
        if not row.transaction_date:
            continue
        if not (getdate(run.from_date) <= getdate(row.transaction_date) <= getdate(run.to_date)):
            continue

        row.pos_profile = resolve_pos_profile(row.terminal_id, row.transaction_date) or row.source_pos_profile or None
        if run.pos_profile and row.pos_profile != run.pos_profile:
            continue
        if wanted_card and card_mapper.alhamrani(row.card_type) != wanted_card:
            continue
        normalized.append(row)

    return normalized


def _base_result(run, bank=None, alhamrani=None, card_mapper=None):
    transaction_date = bank.transaction_date if bank else alhamrani.transaction_date
    terminal_id = bank.terminal_id if bank else alhamrani.terminal_id
    pos_profile = bank.pos_profile if bank else alhamrani.pos_profile
    card_mapper = card_mapper or get_card_type_mapper()
    card_type = card_mapper.bank(bank.card_type) if bank else card_mapper.alhamrani(alhamrani.card_type)
    record_key = _record_key(
        run.name,
        bank_transaction=bank.name if bank else None,
        alhamrani_transaction=alhamrani.name if alhamrani else None,
    )

    bank_amount = flt(bank.transaction_amount, 2) if bank else 0.0
    alhamrani_amount = (
        flt(alhamrani.amount, 2)
        if alhamrani and alhamrani.amount is not None
        else 0.0
    )

    pan_method = get_pan_validation_method(bank, alhamrani) if bank and alhamrani else "Not Available"

    return {
        "name": _record_name(record_key),
        "run": run.name,
        "record_key": record_key,
        "transaction_date": transaction_date,
        "pos_profile": pos_profile,
        "terminal_id": terminal_id,
        "card_type": card_type,
        "bank_transaction": bank.name if bank else None,
        "alhamrani_doctype": ALHAMRANI_DOCTYPE,
        "alhamrani_transaction": alhamrani.name if alhamrani else None,
        "settlement_number": cstr(bank.settlement_number).strip() if bank else None,
        "settlement_date": bank.settlement_date if bank else None,
        "pos_reconciliation_number": cstr(bank.pos_reconciliation_number).strip() if bank else None,
        "bank_commission_amount": flt(bank.fee_amount, 2) if bank else 0.0,
        "bank_commission_vat_amount": flt(bank.vat_amount, 2) if bank else 0.0,
        "bank_settlement_amount": flt(bank.settlement_amount, 2) if bank else 0.0,
        "bank_amount": bank_amount,
        "alhamrani_amount": alhamrani_amount,
        "amount_difference": bank_amount - alhamrani_amount,
        "bank_card_type": card_mapper.bank(bank.card_type) if bank else None,
        "alhamrani_card_type": card_mapper.alhamrani(alhamrani.card_type) if alhamrani else None,
        "bank_masked_pan": bank.masked_card_number if bank else None,
        "alhamrani_masked_pan": alhamrani.masked_pan if alhamrani else None,
        "alhamrani_emv_last4": cstr(getattr(alhamrani, "emv_last4", None)).strip() if alhamrani else None,
        "pan_validation_method": pan_method,
        "bank_transaction_date": bank.transaction_date if bank else None,
        "alhamrani_transaction_date": alhamrani.transaction_date if alhamrani else None,
        "bank_transaction_time": normalize_time(bank.transaction_time) if bank else None,
        "alhamrani_transaction_time": normalize_time(alhamrani.transaction_time) if alhamrani else None,
        "finance_review_status": FINANCE_NOT_REQUIRED,
        "finance_reviewed_by": None,
        "finance_reviewed_on": None,
        "finance_review_note": None,
        "alhamrani_duplicate_count": 0,
    }


def _apply_bank_review(result, bank, reviews):
    review = reviews.get(bank.name)
    result["finance_review_status"] = FINANCE_PENDING

    if not review:
        return

    review_status = cstr(review.finance_review_status).strip()
    if review_status in {FINANCE_APPROVED, FINANCE_INVESTIGATE}:
        result["finance_review_status"] = review_status
        result["finance_reviewed_by"] = review.finance_reviewed_by
        result["finance_reviewed_on"] = review.finance_reviewed_on
        result["finance_review_note"] = review.finance_review_note

    if review.active:
        result.update(
            resolution_status="Manually Cleared",
            manual_clearance_reason=review.reason,
            manual_cleared_by=review.cleared_by,
            manual_cleared_on=review.cleared_on,
        )


def _build_results(run, bank_rows, alhamrani_rows, card_mapper):
    reviews = _bank_review_states()
    integration_dates = _integration_dates()
    alh_by_key = defaultdict(list)
    for row in alhamrani_rows:
        if row.reconciliation_key:
            alh_by_key[row.reconciliation_key].append(row)

    consumed_alh = set()
    results = []
    now = now_datetime()

    for bank in bank_rows:
        candidates = alh_by_key.get(bank.reconciliation_key) or []
        if not candidates:
            result = _base_result(run, bank=bank, card_mapper=card_mapper)
            result.update(
                match_status="Bank Only",
                resolution_status="Pending",
                before_integration=_is_before_integration(bank, integration_dates),
                discrepancy_fields="",
            )
            _apply_bank_review(result, bank, reviews)
            results.append(result)
            continue

        if len(candidates) > 1:
            first = candidates[0]
            consumed_alh.update(row.name for row in candidates)
            result = _base_result(run, bank=bank, alhamrani=first, card_mapper=card_mapper)
            result.update(
                match_status="Discrepancy",
                resolution_status="Pending",
                before_integration=0,
                discrepancy_fields=f"Duplicate Alhamrani key ({len(candidates)} records)",
                alhamrani_duplicate_count=len(candidates),
            )
            results.append(result)
            continue

        alh = candidates[0]
        consumed_alh.add(alh.name)
        discrepancies = compare_transactions(bank, alh, card_mapper=card_mapper)
        result = _base_result(run, bank=bank, alhamrani=alh, card_mapper=card_mapper)
        result.update(
            match_status="Discrepancy" if discrepancies else "Matching",
            resolution_status="Pending" if discrepancies else "Auto Cleared",
            before_integration=0,
            discrepancy_fields=", ".join(discrepancies),
        )
        results.append(result)

    for alh in alhamrani_rows:
        if alh.name in consumed_alh:
            continue
        result = _base_result(run, alhamrani=alh, card_mapper=card_mapper)
        result.update(
            match_status="Alhamrani Only",
            resolution_status="Pending",
            before_integration=0,
            discrepancy_fields=alh.key_error or "",
        )
        results.append(result)

    for row in results:
        row["last_reconciled_on"] = now
        row.setdefault("manual_clearance_reason", None)
        row.setdefault("manual_cleared_by", None)
        row.setdefault("manual_cleared_on", None)

    return results


def _value_equal(left, right):
    if left in (None, "") and right in (None, ""):
        return True
    return cstr(left) == cstr(right)


def _persist_results(run, results):
    existing = frappe.get_all(
        "POS Reconciliation Record",
        filters={"run": run.name},
        fields=["name", "record_key", *RECORD_UPDATE_FIELDS],
        limit_page_length=0,
    )
    existing_by_key = {row.record_key: row for row in existing}
    desired_keys = {row["record_key"] for row in results}

    stale_names = [row.name for row in existing if row.record_key not in desired_keys]
    if stale_names:
        frappe.db.delete("POS Reconciliation Record", {"name": ["in", stale_names]})

    now = now_datetime()
    user = frappe.session.user or "Administrator"
    new_rows = []
    new_fields = [
        "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
        "run", "record_key", *RECORD_UPDATE_FIELDS,
    ]

    for result in results:
        existing_row = existing_by_key.get(result["record_key"])
        if existing_row:
            updates = {}
            for fieldname in RECORD_UPDATE_FIELDS:
                new_value = result.get(fieldname)
                if not _value_equal(existing_row.get(fieldname), new_value):
                    updates[fieldname] = new_value
            if updates:
                frappe.db.set_value(
                    "POS Reconciliation Record",
                    existing_row.name,
                    updates,
                    update_modified=True,
                )
            continue

        values = {
            "name": result["name"],
            "owner": user,
            "creation": now,
            "modified": now,
            "modified_by": user,
            "docstatus": 0,
            "idx": 0,
            "run": run.name,
            "record_key": result["record_key"],
        }
        for fieldname in RECORD_UPDATE_FIELDS:
            values[fieldname] = result.get(fieldname)
        new_rows.append(tuple(values.get(fieldname) for fieldname in new_fields))

    if new_rows:
        frappe.db.bulk_insert(
            "POS Reconciliation Record",
            fields=new_fields,
            values=new_rows,
            chunk_size=1000,
        )


def summarize_results(results):
    summary = {
        "matching_count": 0,
        "discrepancy_count": 0,
        "bank_only_count": 0,
        "alhamrani_only_count": 0,
        "manually_cleared_count": 0,
        "pending_count": 0,
    }
    mapping = {
        "Matching": "matching_count",
        "Discrepancy": "discrepancy_count",
        "Bank Only": "bank_only_count",
        "Alhamrani Only": "alhamrani_only_count",
    }
    for row in results:
        summary[mapping[row["match_status"]]] += 1
        if row["resolution_status"] == "Manually Cleared":
            summary["manually_cleared_count"] += 1
        if row["resolution_status"] == "Pending":
            summary["pending_count"] += 1
    return summary


def refresh_run_summary(run_name):
    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"run": run_name},
        fields=["match_status", "resolution_status"],
        limit_page_length=0,
    )
    summary = summarize_results(rows)
    frappe.db.set_value("POS Reconciliation Run", run_name, summary, update_modified=True)
    return summary


def execute_run(run_name):
    run = frappe.get_doc("POS Reconciliation Run", run_name)
    run.check_permission("write")
    run.validate_date_range()

    frappe.db.set_value("POS Reconciliation Run", run.name, "status", "Running", update_modified=True)

    card_mapper = get_card_type_mapper()
    bank_rows = _bank_rows(run, card_mapper)
    alhamrani_rows = _alhamrani_rows(run, card_mapper)
    results = _build_results(run, bank_rows, alhamrani_rows, card_mapper)
    _persist_results(run, results)

    summary = summarize_results(results)
    summary.update(
        bank_transaction_count=len(bank_rows),
        alhamrani_transaction_count=len(alhamrani_rows),
        status="Completed",
        last_reconciled_on=now_datetime(),
    )
    frappe.db.set_value("POS Reconciliation Run", run.name, summary, update_modified=True)
    return {"run": run.name, **summary}
