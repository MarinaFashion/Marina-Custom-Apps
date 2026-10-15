from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cstr, flt, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.bank_statement_reconciliation_service import (
    _finalize_settlement,
    _load_or_create_settlement,
    normalize_settlement_number,
    normalize_statement_card_type,
    normalize_terminal_reference,
    terminal_bank_reference,
)

RECORD_DOCTYPE = "POS Reconciliation Record"
BANK_POS_DOCTYPE = "Bank POS Transaction"
STATEMENT_DOCTYPE = "Marina Bank Statement Transaction"
SETTLEMENT_DOCTYPE = "POS Bank Settlement"
SETTINGS_DOCTYPE = "POS Reconciliation Settings"


def _chunks(values, size=500):
    values = list(values or [])
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _run_records(run_name):
    return frappe.get_all(
        RECORD_DOCTYPE,
        filters={"run": run_name},
        fields=[
            "name",
            "bank_transaction",
            "match_status",
            "resolution_status",
            "transaction_date",
            "pos_profile",
            "terminal_id",
            "card_type",
        ],
        limit_page_length=0,
    )


def _bank_source_map(bank_names):
    if not bank_names:
        return {}
    out = {}
    for chunk in _chunks(bank_names):
        rows = frappe.get_all(
            BANK_POS_DOCTYPE,
            filters={"name": ["in", chunk]},
            fields=[
                "name",
                "transaction_amount",
                "fee_amount",
                "vat_amount",
                "settlement_number",
                "settlement_date",
                "pos_profile",
                "terminal_id",
                "balance_date",
                "card_type",
            ],
            limit_page_length=0,
        )
        out.update({row.name: row for row in rows})
    return out


def _record_groups(run, records):
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    ref_length = settings.get("bank_statement_terminal_reference_length") or 8
    bank_names = [row.bank_transaction for row in records if row.bank_transaction]
    source = _bank_source_map(bank_names)

    groups = defaultdict(list)
    record_key = {}
    missing_identity = 0

    for record in records:
        if not record.bank_transaction:
            continue
        bank = source.get(record.bank_transaction)
        if not bank:
            continue

        settlement_number = normalize_settlement_number(bank.settlement_number)
        terminal_id = cstr(bank.terminal_id or record.terminal_id).strip()
        card_type = normalize_statement_card_type(record.card_type or bank.card_type)
        reconciliation_date = getdate(bank.balance_date) if bank.balance_date else None
        terminal_ref = terminal_bank_reference(terminal_id, ref_length) if terminal_id else ""

        if not settlement_number or not terminal_ref or not card_type or not reconciliation_date:
            missing_identity += 1
            continue

        key = (
            settlement_number,
            normalize_terminal_reference(terminal_ref),
            reconciliation_date,
            card_type,
        )
        record_key[record.name] = key
        groups[key].append(
            frappe._dict(
                reconciliation_record=record.name,
                bank_pos_transaction=bank.name,
                transaction_date=record.transaction_date,
                reconciliation_date=reconciliation_date,
                pos_profile=bank.pos_profile or record.pos_profile,
                terminal_id=terminal_id,
                bank_terminal_reference=terminal_ref,
                card_type=card_type,
                settlement_number=settlement_number,
                settlement_date=bank.settlement_date,
                gross_amount=flt(bank.transaction_amount, 2),
                commission_amount=flt(bank.fee_amount, 2),
                vat_amount=flt(bank.vat_amount, 2),
            )
        )

    return groups, record_key, missing_identity


def _statement_rows(run):
    if not run.bank_account:
        return []
    filters = {
        "bank_account": run.bank_account,
        "is_pos_statement_line": 1,
        "reconciliation_date": ["between", [run.from_date, run.to_date]],
    }
    return frappe.get_all(
        STATEMENT_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "processing_date",
            "reference_number",
            "debit",
            "credit",
            "description",
            "statement_code",
            "component",
            "settlement_number",
            "bank_terminal_reference",
            "reconciliation_date",
            "card_type",
            "reconciliation_status",
            "pos_reconciliation_run",
            "pos_bank_settlement",
        ],
        order_by="reconciliation_date asc, processing_date asc, name asc",
        limit_page_length=0,
    )


def _statement_key(row):
    return (
        normalize_settlement_number(row.settlement_number),
        normalize_terminal_reference(row.bank_terminal_reference),
        getdate(row.reconciliation_date) if row.reconciliation_date else None,
        normalize_statement_card_type(row.card_type),
    )


def _statement_amount(row):
    credit = abs(flt(row.credit, 2))
    debit = abs(flt(row.debit, 2))
    if cstr(row.component).strip() == "Gross":
        return credit or debit, "Deposit" if credit else "Withdrawal"
    return debit or credit, "Withdrawal" if debit else "Deposit"


def _reset_previous_run_links(run_name):
    rows = frappe.get_all(
        STATEMENT_DOCTYPE,
        filters={"pos_reconciliation_run": run_name},
        fields=["name", "debit", "credit"],
        limit_page_length=0,
    )
    for row in rows:
        amount = abs(flt(row.debit, 2)) or abs(flt(row.credit, 2))
        frappe.db.set_value(
            STATEMENT_DOCTYPE,
            row.name,
            {
                "reconciliation_status": "Unreconciled",
                "allocated_amount": 0,
                "remaining_amount": amount,
                "pos_reconciliation_run": None,
                "pos_bank_settlement": None,
                "reconciled_on": None,
                "reconciled_by": None,
            },
            update_modified=False,
        )


def _mark_statement_rows(rows, settlement, run_name, fully_reconciled, checked_on):
    status = "Reconciled" if fully_reconciled else "Partially Reconciled"
    for row in rows:
        amount = abs(flt(row.debit, 2)) or abs(flt(row.credit, 2))
        frappe.db.set_value(
            STATEMENT_DOCTYPE,
            row.name,
            {
                "reconciliation_status": status,
                "transaction_category": "POS Settlement",
                "allocated_amount": amount if fully_reconciled else 0,
                "remaining_amount": 0 if fully_reconciled else amount,
                "pos_reconciliation_run": run_name,
                "pos_bank_settlement": settlement.name,
                "reconciled_on": checked_on if fully_reconciled else None,
                "reconciled_by": frappe.session.user if fully_reconciled else None,
            },
            update_modified=False,
        )


def _update_records(run, records, record_keys, settlements, evidence, checked_on):
    for record in records:
        key = record_keys.get(record.name)
        if not key:
            frappe.db.set_value(
                RECORD_DOCTYPE,
                record.name,
                {
                    "bank_statement_status": "Not Checked",
                    "bank_statement_reconciliation": run.name,
                    "bank_statement_settlement": None,
                    "bank_statement_references": None,
                    "bank_statement_checked_on": checked_on,
                },
                update_modified=False,
            )
            continue

        settlement = settlements.get(key)
        statement_rows = evidence.get(key) or []
        refs = ", ".join(row.name for row in statement_rows) or None

        if settlement and settlement.status == "Fully Reconciled":
            statement_status = "Fully Reconciled"
        elif statement_rows:
            statement_status = "Exception"
        else:
            statement_status = "Not Found"

        updates = {
            "bank_statement_status": statement_status,
            "bank_statement_reconciliation": run.name,
            "bank_statement_settlement": settlement.name if settlement else None,
            "bank_statement_references": refs,
            "bank_statement_checked_on": checked_on,
        }

        current_match = cstr(record.match_status).strip()
        current_resolution = cstr(record.resolution_status).strip()

        if current_match in {"Matching Not Settled", "Fully Matching", "Matching"}:
            if statement_status == "Fully Reconciled":
                updates["match_status"] = "Fully Matching"
                updates["resolution_status"] = "Auto Cleared"
            else:
                updates["match_status"] = "Matching Not Settled"
                updates["resolution_status"] = "Pending"
        elif current_match in {"Bank Only", "Bank Only - Settled", "Bank Only - Not Settled"}:
            updates["match_status"] = (
                "Bank Only - Settled"
                if statement_status == "Fully Reconciled"
                else "Bank Only - Not Settled"
            )
            if current_resolution == "Manually Cleared":
                # Preserve historical Finance approval. New approvals are allowed
                # only after the statement settlement becomes Fully Reconciled.
                updates["resolution_status"] = "Manually Cleared"
            else:
                updates["resolution_status"] = "Pending"
        elif current_match in {"Discrepancy", "Alhamrani Only"}:
            updates["resolution_status"] = "Pending"

        frappe.db.set_value(
            RECORD_DOCTYPE,
            record.name,
            updates,
            update_modified=False,
        )


def reconcile_run_statement(run):
    if not run.bank_account:
        return {
            "statement_transaction_count": 0,
            "statement_reconciled_count": 0,
            "statement_unreconciled_count": 0,
            "statement_pos_line_count": 0,
            "statement_settlement_count": 0,
            "statement_fully_reconciled_settlements": 0,
            "statement_missing_identity_count": 0,
        }

    records = _run_records(run.name)
    groups, record_keys, missing_identity = _record_groups(run, records)
    _reset_previous_run_links(run.name)

    settlements = {}
    for key, rows in groups.items():
        settlement_key = "|".join(
            [
                cstr(run.bank_account),
                key[0],
                key[1],
                cstr(key[2]),
                key[3],
            ]
        )
        doc = _load_or_create_settlement(
            run.name,
            run.bank_account,
            settlement_key,
            rows,
        )
        settlements[key] = doc

    statement_rows = _statement_rows(run)
    evidence = defaultdict(list)
    for row in statement_rows:
        evidence[_statement_key(row)].append(row)

    checked_on = now_datetime()

    for key, settlement in settlements.items():
        settlement.set("statement_matches", [])
        rows = evidence.get(key) or []
        for row in rows:
            amount, direction = _statement_amount(row)
            settlement.append(
                "statement_matches",
                {
                    "bank_transaction": row.name,
                    "transaction_date": row.processing_date,
                    "component": row.component,
                    "direction": direction,
                    "statement_amount": amount,
                    "reference_number": row.reference_number,
                    "description": row.description,
                    "match_status": "Parsed",
                },
            )
        _finalize_settlement(settlement, 0.01)
        _mark_statement_rows(
            rows,
            settlement,
            run.name,
            settlement.status == "Fully Reconciled",
            checked_on,
        )

    _update_records(run, records, record_keys, settlements, evidence, checked_on)

    period_statement_count = frappe.db.count(
        STATEMENT_DOCTYPE,
        filters={
            "bank_account": run.bank_account,
            "processing_date": ["between", [run.from_date, run.to_date]],
        },
    )
    reconciled_count = frappe.db.count(
        STATEMENT_DOCTYPE,
        filters={
            "bank_account": run.bank_account,
            "processing_date": ["between", [run.from_date, run.to_date]],
            "reconciliation_status": "Reconciled",
        },
    )

    return {
        "statement_transaction_count": period_statement_count,
        "statement_reconciled_count": reconciled_count,
        "statement_unreconciled_count": max(period_statement_count - reconciled_count, 0),
        "statement_pos_line_count": len(statement_rows),
        "statement_settlement_count": len(settlements),
        "statement_fully_reconciled_settlements": sum(
            1 for doc in settlements.values() if doc.status == "Fully Reconciled"
        ),
        "statement_missing_identity_count": missing_identity,
    }
