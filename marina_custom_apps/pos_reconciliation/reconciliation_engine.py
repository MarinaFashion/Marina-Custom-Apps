from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, now_datetime

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


def _time_difference_seconds(bank_date, bank_time, alh_date, alh_time):
    """Compare actual date+time; do not wrap a real date mismatch across midnight."""
    try:
        left = datetime.combine(getdate(bank_date), datetime.strptime(bank_time, "%H:%M:%S").time())
        right = datetime.combine(getdate(alh_date), datetime.strptime(alh_time, "%H:%M:%S").time())
    except (ValueError, TypeError):
        return None
    return abs((left - right).total_seconds())


def compare_transactions(bank, alhamrani, card_mapper=None, time_tolerance_seconds=60):
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
    if bank_time and alh_time:
        delta = _time_difference_seconds(bank_date, bank_time, alh_date, alh_time)
        if delta is None or delta > max(0, min(cint(time_tolerance_seconds), 300)):
            discrepancies.append("Transaction Time")

    return discrepancies


def _record_name(record_key):
    digest = hashlib.sha1(record_key.encode("utf-8")).hexdigest()[:20].upper()
    return f"PREC-{digest}"


def _record_key(run_name=None, bank_transaction=None, alhamrani_transaction=None):
    """Stable source identity, independent of how many executions cover it."""
    if bank_transaction:
        return f"BANK|{bank_transaction}"
    if alhamrani_transaction:
        return f"ALHAMRANI|{alhamrani_transaction}"
    frappe.throw(_("Reconciliation records require a source transaction."))



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
            "rrn",
            "transaction_type",
            "transaction_status",
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


def _alhamrani_rows(run, card_mapper, bank_rows=None, manual_links=None):
    """Load run-scoped Alhamrani rows and explicitly linked counterparts.

    A bank transaction within a filtered run can have a deliberately approved
    manual link to an Alhamrani row with a different POS Profile (or Card
    Type). Include only THAT linked source outside the normal filters so the
    approved pair is reconciled rather than incorrectly shown as Bank Only.
    """
    adapter = AlhamraniAdapter()
    normalized = []
    wanted_card = card_mapper.resolve(run.card_type) if run.card_type else None
    manual_links = manual_links or {}
    linked_source_names = {
        manual_links[bank.name]
        for bank in (bank_rows or [])
        if bank.name in manual_links
    }

    for raw in adapter.get_rows(run.from_date, run.to_date):
        if not adapter.is_approved(raw):
            continue
        row = adapter.normalized_row(raw)
        if not row.transaction_date:
            continue
        if not (getdate(run.from_date) <= getdate(row.transaction_date) <= getdate(run.to_date)):
            continue

        row.pos_profile = resolve_pos_profile(row.terminal_id, row.transaction_date) or row.source_pos_profile or None
        explicitly_linked = row.name in linked_source_names
        if run.pos_profile and row.pos_profile != run.pos_profile and not explicitly_linked:
            continue
        if wanted_card and card_mapper.alhamrani(row.card_type) != wanted_card and not explicitly_linked:
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
        "alhamrani_duplicate_count": 0,
    }



def _automatic_alhamrani_keys(alhamrani_rows):
    """Index only real terminal responses; manual slips require an approved link.

    Never auto-match a manually confirmed source even if bank-sourced enrichment
    later completes its Terminal ID, Auth Code, PAN, or other payment fields.
    """
    by_key = defaultdict(list)
    for row in alhamrani_rows:
        if row.reconciliation_key and not row.manual_confirmation:
            by_key[row.reconciliation_key].append(row)
    return by_key


def _build_results(run, bank_rows, alhamrani_rows, card_mapper, time_tolerance_seconds=60, manual_links=None):
    from marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service import active_manual_links, validate_manual_pair
    if manual_links is None:
        manual_links = active_manual_links()
    manual_alh = {alh for alh in manual_links.values()}
    if len(manual_alh) != len(manual_links):
        frappe.throw(_("Duplicate active manual Alhamrani source link found."))
    alh_by_name = {row.name: row for row in alhamrani_rows}
    integration_dates = _integration_dates()
    alh_by_key = _automatic_alhamrani_keys(alhamrani_rows)

    consumed_alh = set()
    results = []
    now = now_datetime()

    for bank in bank_rows:
        if bank.name in manual_links:
            linked = alh_by_name.get(manual_links[bank.name])
            if not linked:
                # Scope/date/status filters can omit the linked Alhamrani row.
                # Do not abort the entire run or falsely recognize an unavailable pair.
                result = _base_result(run, bank=bank, card_mapper=card_mapper)
                result.update(
                    match_status="Bank Only - Not Settled",
                    resolution_status="Pending",
                    before_integration=_is_before_integration(bank, integration_dates),
                    discrepancy_fields="Manual Link: Alhamrani transaction unavailable in this run",
                )
                results.append(result)
                continue
            validate_manual_pair(bank, linked)
            candidates = [linked]
        else:
            candidates = [r for r in (alh_by_key.get(bank.reconciliation_key) or []) if r.name not in manual_alh]
        if not candidates:
            result = _base_result(run, bank=bank, card_mapper=card_mapper)
            result.update(
                match_status="Bank Only - Not Settled",
                resolution_status="Pending",
                before_integration=_is_before_integration(bank, integration_dates),
                discrepancy_fields="",
            )
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
        if bank.name in manual_links:
            # The terminal response was lost. Manual approval already verifies RRN,
            # amount, date, store, and transaction type. Do not infer missing PAN/card/time.
            discrepancies = []
        else:
            discrepancies = compare_transactions(bank, alh, card_mapper=card_mapper, time_tolerance_seconds=time_tolerance_seconds)
        result = _base_result(run, bank=bank, alhamrani=alh, card_mapper=card_mapper)
        result.update(
            match_status="Discrepancy" if discrepancies else "Matching Not Settled",
            resolution_status="Pending",
            before_integration=0,
            discrepancy_fields=", ".join(discrepancies),
        )
        results.append(result)

    for alh in alhamrani_rows:
        if alh.name in consumed_alh:
            continue
        result = _base_result(run, alhamrani=alh, card_mapper=card_mapper)
        if alh.manual_confirmation:
            # Explain why a complete/enriched key did not trigger auto-matching.
            discrepancy = (
                "Manual confirmation: linked Bank POS not in this run"
                if alh.name in manual_alh
                else "Manual confirmation: approved link required"
            )
        else:
            discrepancy = alh.key_error or ""
        result.update(
            match_status="Alhamrani Only",
            resolution_status="Pending",
            before_integration=0,
            discrepancy_fields=discrepancy,
        )
        results.append(result)

    for row in results:
        row["last_reconciled_on"] = now

    return results


def _value_equal(left, right):
    if left in (None, "") and right in (None, ""):
        return True
    return cstr(left) == cstr(right)


def _existing_records_for_scope(bank_rows, alhamrani_rows):
    """Retrieve only affected source rows via indexed transaction identifiers."""
    fields = list(dict.fromkeys(
        ["name", "record_key", "accounting_status", "accounting_posting", "journal_entry"]
        + list(RECORD_UPDATE_FIELDS)
    ))
    found = {}
    for fieldname, rows in (("bank_transaction", bank_rows), ("alhamrani_transaction", alhamrani_rows)):
        names = list({row.name for row in rows})
        for i in range(0, len(names), 500):
            for row in frappe.get_all(
                "POS Reconciliation Record",
                filters={fieldname: ["in", names[i:i + 500]]},
                fields=fields,
                limit_page_length=0,
            ):
                found[row.name] = row
    return list(found.values())


def _protected_change_details(current, proposed):
    """Return changes that may affect a protected financial/source match.

    Card mapping aliases and the resulting Card Type-only discrepancy are
    descriptive, not accounting evidence. Never accept new source pairings,
    settlement changes, amount changes, or unrelated match-state changes.
    """
    financial_fields = (
        "bank_transaction", "alhamrani_transaction", "bank_amount",
        "alhamrani_amount", "bank_commission_amount", "bank_commission_vat_amount",
        "settlement_number", "settlement_date", "bank_settlement_amount",
        "terminal_id",
    )
    changes = [
        (field, current.get(field), proposed.get(field))
        for field in financial_fields
        if not _value_equal(current.get(field), proposed.get(field))
    ]

    def non_card_discrepancies(value):
        return sorted(
            part.strip() for part in cstr(value).split(",")
            if part.strip() and part.strip() != "Card Type"
        )

    old_discrepancies = non_card_discrepancies(current.get("discrepancy_fields"))
    new_discrepancies = non_card_discrepancies(proposed.get("discrepancy_fields"))
    if old_discrepancies != new_discrepancies:
        changes.append(("discrepancy_fields", current.get("discrepancy_fields"), proposed.get("discrepancy_fields")))

    # The statement integration promotes Not Settled statuses after matching.
    equivalences = {
        "Fully Matching": "Matching Not Settled",
        "Bank Only - Settled": "Bank Only - Not Settled",
    }
    old_status = equivalences.get(cstr(current.match_status), cstr(current.match_status))
    new_status = cstr(proposed.get("match_status"))
    if old_status != new_status:
        # Only the classification transition from/to Card Type discrepancy
        # is safe. Even then, the underlying non-card discrepancies must agree.
        card_classification_statuses = {"Discrepancy", "Matching Not Settled"}
        old_has_card = "Card Type" in [x.strip() for x in cstr(current.get("discrepancy_fields")).split(",")]
        new_has_card = "Card Type" in [x.strip() for x in cstr(proposed.get("discrepancy_fields")).split(",")]
        card_only_transition = (
            {old_status, new_status} <= card_classification_statuses
            and old_discrepancies == new_discrepancies == []
            and old_has_card != new_has_card
        )
        if not card_only_transition:
            changes.append(("match_status", current.match_status, proposed.get("match_status")))
    return changes


def _material_change(current, proposed):
    return bool(_protected_change_details(current, proposed))


def _protected_result(row):
    return bool(
        row.accounting_posting or row.journal_entry
        or cstr(row.accounting_status) in {
            "Posted", "Draft Created", "Draft - Review Required", "Posted - Review Required"
        }
    )


def _persist_results(run, results, bank_rows, alhamrani_rows, execution_name=None):
    """Upsert global current results, without deleting data outside this execution."""
    from marina_custom_apps.pos_reconciliation.period_control import assert_dates_open

    assert_dates_open([row.transaction_date for row in bank_rows] + [
        row.transaction_date for row in alhamrani_rows
    ])
    existing = _existing_records_for_scope(bank_rows, alhamrani_rows)
    existing_by_key = {row.record_key: row for row in existing}
    desired = {row["record_key"] for row in results}
    if len(desired) != len(results):
        frappe.throw(_("Duplicate reconciliation source keys in the same execution."))

    stale = [row for row in existing if row.record_key not in desired]
    for row in stale:
        if _protected_result(row):
            frappe.throw(
                _("Existing result {0} has accounting or posting evidence. Reset/reverse it before changing its source pairing.").format(row.name)
            )
        for child in ("POS Accounting Posting Item", "POS Bank Settlement Transaction"):
            if frappe.db.exists(child, {"reconciliation_record": row.name}):
                frappe.throw(
                    _("Existing result {0} is referenced by {1}.").format(row.name, child)
                )

    if stale:
        frappe.db.delete("POS Reconciliation Record", {"name": ["in", [row.name for row in stale]]})

    now = now_datetime()
    user = frappe.session.user or "Administrator"
    fields = [
        "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
        "run", "record_key", "last_execution", *RECORD_UPDATE_FIELDS,
    ]
    no_reset_if_protected = {"match_status", "resolution_status"}
    new_rows = []
    for result in results:
        existing_row = existing_by_key.get(result["record_key"])
        if existing_row:
            if _protected_result(existing_row):
                protected_changes = _protected_change_details(existing_row, result)
                if protected_changes:
                    details = "; ".join(
                        "{0}: {1} -> {2}".format(field, cstr(before)[:80], cstr(after)[:80])
                        for field, before, after in protected_changes[:5]
                    )
                    frappe.throw(
                        _("Result {0} has protected accounting evidence. Reconciliation cannot change: {1}. Resolve the financial or source-pairing change before rerunning.").format(
                            existing_row.name, details
                        )
                    )
            updates = {}
            for fieldname in RECORD_UPDATE_FIELDS:
                if _protected_result(existing_row) and fieldname in no_reset_if_protected:
                    continue
                val = result.get(fieldname)
                if not _value_equal(existing_row.get(fieldname), val):
                    updates[fieldname] = val
            if execution_name:
                updates["last_execution"] = execution_name
            if updates:
                frappe.db.set_value(
                    "POS Reconciliation Record", existing_row.name, updates,
                    update_modified=True,
                )
            continue
        row = {
            "name": result["name"], "owner": user, "creation": now,
            "modified": now, "modified_by": user, "docstatus": 0, "idx": 0,
            "run": run.name, "record_key": result["record_key"],
            "last_execution": execution_name,
        }
        for fieldname in RECORD_UPDATE_FIELDS:
            row[fieldname] = result.get(fieldname)
        new_rows.append(tuple(row.get(fieldname) for fieldname in fields))

    if new_rows:
        frappe.db.bulk_insert(
            "POS Reconciliation Record", fields=fields, values=new_rows, chunk_size=1000
        )


def summarize_results(results):
    summary = {
        "matching_count": 0,
        "matching_not_settled_count": 0,
        "discrepancy_count": 0,
        "bank_only_count": 0,
        "bank_only_settled_count": 0,
        "bank_only_not_settled_count": 0,
        "alhamrani_only_count": 0,
        "pending_count": 0,
    }
    mapping = {
        "Fully Matching": "matching_count",
        "Matching Not Settled": "matching_not_settled_count",
        "Matching": "matching_not_settled_count",
        "Discrepancy": "discrepancy_count",
        "Bank Only - Settled": "bank_only_settled_count",
        "Bank Only - Not Settled": "bank_only_not_settled_count",
        "Bank Only": "bank_only_not_settled_count",
        "Alhamrani Only": "alhamrani_only_count",
    }
    for row in results:
        bucket = mapping.get(row["match_status"])
        if bucket:
            summary[bucket] += 1
        if row["match_status"] in {"Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"}:
            summary["bank_only_count"] += 1
        if row["resolution_status"] == "Pending":
            summary["pending_count"] += 1
    return summary


def _set_run_values(run_name, values):
    """Write controller state to tabSingles (never tabPOS Reconciliation Run)."""
    if run_name != "POS Reconciliation Run":
        frappe.throw(_("Invalid reconciliation control name."))
    meta = frappe.get_meta("POS Reconciliation Run")
    for fieldname, value in (values or {}).items():
        if meta.has_field(fieldname):
            frappe.db.set_single_value("POS Reconciliation Run", fieldname, value)


def refresh_run_summary(run_name):
    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"run": run_name},
        fields=["match_status", "resolution_status"],
        limit_page_length=0,
    )
    summary = summarize_results(rows)
    _set_run_values(run_name, summary)
    return summary


def execute_run(run, execution_name=None):
    """Execute the immutable scope captured in POS Reconciliation Execution."""
    from marina_custom_apps.pos_reconciliation.period_control import assert_scope_open
    assert_scope_open(run.from_date, run.to_date)

    card_mapper = get_card_type_mapper()
    from marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service import active_manual_links
    # Fetch the approved manual links just once per execution, and use the
    # same immutable view for source selection and the reconciliation matcher.
    manual_links = active_manual_links()
    bank_rows = _bank_rows(run, card_mapper)
    alhamrani_rows = _alhamrani_rows(run, card_mapper, bank_rows=bank_rows, manual_links=manual_links)
    settings = frappe.get_single('POS Reconciliation Settings')
    configured = settings.get('transaction_time_tolerance_seconds')
    time_tolerance = max(0, min(cint(60 if configured is None else configured), 300))
    results = _build_results(
        run, bank_rows, alhamrani_rows, card_mapper,
        time_tolerance_seconds=time_tolerance, manual_links=manual_links,
    )
    _persist_results(run, results, bank_rows, alhamrani_rows, execution_name)

    # Never carry a previous execution's statement counters into a no-bank run.
    statement_summary = {
        "statement_transaction_count": 0,
        "statement_reconciled_count": 0,
        "statement_unreconciled_count": 0,
        "statement_pos_line_count": 0,
        "statement_settlement_count": 0,
        "statement_fully_reconciled_settlements": 0,
        "statement_missing_identity_count": 0,
    }
    if run.get("bank_account"):
        from marina_custom_apps.pos_reconciliation.unified_statement_reconciliation import (
            reconcile_run_statement,
        )
        statement_summary = reconcile_run_statement(run)

    summary = refresh_run_summary(run.name)
    summary.update(
        bank_transaction_count=len(bank_rows),
        alhamrani_transaction_count=len(alhamrani_rows),
        last_reconciled_on=now_datetime(),
        **statement_summary,
    )
    _set_run_values(run.name, summary)
    # Synchronize only this execution's source transactions, not all history.
    from marina_custom_apps.pos_reconciliation.accounting_service import (
        sync_accounting_status_for_bank_transactions,
    )
    sync_accounting_status_for_bank_transactions([row.name for row in bank_rows])
    return {"run": run.name, **summary}
