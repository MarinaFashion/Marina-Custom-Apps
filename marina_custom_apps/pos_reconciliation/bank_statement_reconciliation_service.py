from __future__ import annotations

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.accounting_service import (
    is_reconciliation_confirmed,
)

RECORD_DOCTYPE = "POS Reconciliation Record"
BANK_POS_DOCTYPE = "Bank POS Transaction"
STANDARD_BANK_DOCTYPE = "Bank Transaction"
SETTLEMENT_DOCTYPE = "POS Bank Settlement"
SETTINGS_DOCTYPE = "POS Reconciliation Settings"

_RECON_RE = re.compile(r"RECON\s*NO\.?\s*:?\s*0*(\d+)", re.I)
_REFERENCE_RE = re.compile(r"REFERENCE\s*:?\s*([0-9]{4,})", re.I)


def normalize_settlement_number(value):
    value = cstr(value).strip()
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    return str(int(digits)) if digits else value.upper()


def normalize_terminal_reference(value):
    return re.sub(r"\D", "", cstr(value))


def terminal_bank_reference(terminal_id, length):
    digits = normalize_terminal_reference(terminal_id)
    if not digits:
        return cstr(terminal_id).strip()
    length = max(int(length or 8), 1)
    return digits[:length]


def _mapping_rows():
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    rows = []
    for row in settings.get("bank_statement_code_mappings") or []:
        if not row.active:
            continue
        code = cstr(row.code).strip().upper()
        card_type = cstr(row.card_type).strip().upper()
        component = cstr(row.component).strip()
        if code and card_type and component:
            rows.append((code, card_type, component))
    rows.sort(key=lambda item: len(item[0]), reverse=True)
    return rows


def parse_pos_statement_text(text, mappings=None):
    text = cstr(text)
    recon_match = _RECON_RE.search(text)
    reference_match = _REFERENCE_RE.search(text)
    if not recon_match or not reference_match:
        return None

    upper = text.upper()
    mappings = mappings if mappings is not None else _mapping_rows()
    chosen = None
    for code, card_type, component in mappings:
        pattern = rf"\b{re.escape(code)}(?:\d{{6,8}})?\b"
        if re.search(pattern, upper):
            chosen = (code, card_type, component)
            break
    if not chosen:
        return None

    code, card_type, component = chosen
    return frappe._dict(
        settlement_number=normalize_settlement_number(recon_match.group(1)),
        bank_terminal_reference=normalize_terminal_reference(reference_match.group(1)),
        statement_code=code,
        card_type=card_type,
        component=component,
    )


def _latest_reconciliation_rows(from_date, to_date):
    rows = frappe.get_all(
        RECORD_DOCTYPE,
        filters={
            "transaction_date": ["between", [from_date, to_date]],
            "bank_transaction": ["is", "set"],
        },
        fields=[
            "name",
            "bank_transaction",
            "transaction_date",
            "pos_profile",
            "terminal_id",
            "card_type",
            "match_status",
            "resolution_status",
            "last_reconciled_on",
            "modified",
        ],
        order_by="bank_transaction asc, last_reconciled_on desc, modified desc, name desc",
        limit_page_length=0,
    )

    latest = {}
    for row in rows:
        if row.bank_transaction and row.bank_transaction not in latest:
            latest[row.bank_transaction] = row
    return list(latest.values())


def _source_groups(bank_account, from_date, to_date, terminal_ref_length):
    latest_rows = _latest_reconciliation_rows(from_date, to_date)
    confirmed = [
        row
        for row in latest_rows
        if is_reconciliation_confirmed(row.match_status, row.resolution_status)
    ]
    if not confirmed:
        return {}, 0

    bank_names = [row.bank_transaction for row in confirmed if row.bank_transaction]
    bank_map = {
        row.name: row
        for row in frappe.get_all(
            BANK_POS_DOCTYPE,
            filters={"name": ["in", bank_names]},
            fields=[
                "name",
                "transaction_status",
                "transaction_amount",
                "fee_amount",
                "vat_amount",
                "settlement_number",
                "settlement_date",
                "pos_profile",
                "terminal_id",
            ],
            limit_page_length=0,
        )
    }

    groups = defaultdict(list)
    missing_settlement = 0
    for record in confirmed:
        bank = bank_map.get(record.bank_transaction)
        if not bank:
            continue
        if cstr(bank.transaction_status).strip().upper() != "APPROVED":
            continue

        settlement_number = normalize_settlement_number(bank.settlement_number)
        terminal_id = cstr(bank.terminal_id or record.terminal_id).strip()
        card_type = cstr(record.card_type).strip().upper()
        if not settlement_number:
            missing_settlement += 1
            continue
        if not terminal_id or not card_type:
            missing_settlement += 1
            continue

        ref = terminal_bank_reference(terminal_id, terminal_ref_length)
        key = "|".join([bank_account, settlement_number, ref, card_type])
        groups[key].append(
            frappe._dict(
                reconciliation_record=record.name,
                bank_pos_transaction=bank.name,
                transaction_date=record.transaction_date,
                pos_profile=bank.pos_profile or record.pos_profile,
                terminal_id=terminal_id,
                bank_terminal_reference=ref,
                card_type=card_type,
                settlement_number=settlement_number,
                settlement_date=bank.settlement_date,
                gross_amount=flt(bank.transaction_amount, 2),
                commission_amount=flt(bank.fee_amount, 2),
                vat_amount=flt(bank.vat_amount, 2),
            )
        )
    return groups, missing_settlement


def _load_or_create_settlement(reconciliation_run, bank_account, key, rows):
    name = frappe.db.get_value(SETTLEMENT_DOCTYPE, {"settlement_key": key}, "name")
    if name:
        doc = frappe.get_doc(SETTLEMENT_DOCTYPE, name)
        doc.set("transactions", [])
        doc.set("statement_matches", [])
    else:
        doc = frappe.new_doc(SETTLEMENT_DOCTYPE)

    first = rows[0]
    settlement_dates = [getdate(row.settlement_date) for row in rows if row.settlement_date]
    profiles = {cstr(row.pos_profile).strip() for row in rows if cstr(row.pos_profile).strip()}

    doc.reconciliation_run = reconciliation_run
    doc.settlement_key = key
    doc.settlement_number = first.settlement_number
    doc.settlement_date = max(settlement_dates) if settlement_dates else None
    doc.bank_account = bank_account
    doc.pos_profile = next(iter(profiles)) if len(profiles) == 1 else None
    doc.terminal_id = first.terminal_id
    doc.bank_terminal_reference = first.bank_terminal_reference
    doc.card_type = first.card_type
    doc.transaction_count = len(rows)
    doc.gross_amount = flt(sum(row.gross_amount for row in rows), 2)
    doc.commission_amount = flt(sum(row.commission_amount for row in rows), 2)
    doc.vat_amount = flt(sum(row.vat_amount for row in rows), 2)
    doc.expected_net = flt(doc.gross_amount - doc.commission_amount - doc.vat_amount, 2)
    doc.statement_gross_amount = 0
    doc.statement_commission_amount = 0
    doc.statement_vat_amount = 0
    doc.statement_net_amount = 0
    doc.gross_difference = flt(-doc.gross_amount, 2)
    doc.commission_difference = flt(-doc.commission_amount, 2)
    doc.vat_difference = flt(-doc.vat_amount, 2)
    doc.net_difference = flt(-doc.expected_net, 2)
    doc.status = "ERP Settlement Only"

    for row in rows:
        doc.append(
            "transactions",
            {
                "reconciliation_record": row.reconciliation_record,
                "bank_pos_transaction": row.bank_pos_transaction,
                "transaction_date": row.transaction_date,
                "pos_profile": row.pos_profile,
                "terminal_id": row.terminal_id,
                "card_type": row.card_type,
                "gross_amount": row.gross_amount,
                "commission_amount": row.commission_amount,
                "vat_amount": row.vat_amount,
            },
        )

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return doc


def _statement_rows(bank_account, from_date, to_date):
    fields = [
        "name",
        "date",
        "description",
        "reference_number",
        "transaction_type",
        "bank_party_name",
        "deposit",
        "withdrawal",
        "status",
    ]
    meta = frappe.get_meta(STANDARD_BANK_DOCTYPE)
    for fieldname in (
        "custom_description_extra",
        "description_extra",
        "custom_remarks",
        "remarks",
    ):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    return frappe.get_all(
        STANDARD_BANK_DOCTYPE,
        filters={
            "bank_account": bank_account,
            "date": ["between", [from_date, to_date]],
            "docstatus": 1,
        },
        fields=fields,
        order_by="date asc, name asc",
        limit_page_length=0,
    )


def _statement_text(row):
    values = [
        row.get("description"),
        row.get("custom_description_extra"),
        row.get("description_extra"),
        row.get("reference_number"),
        row.get("transaction_type"),
        row.get("bank_party_name"),
        row.get("custom_remarks"),
        row.get("remarks"),
    ]
    return " ".join(
        cstr(value).strip()
        for value in values
        if cstr(value).strip()
    )


def _component_amount(row, component):
    deposit = abs(flt(row.deposit, 2))
    withdrawal = abs(flt(row.withdrawal, 2))
    if component == "Gross":
        return deposit or withdrawal, "Deposit" if deposit else "Withdrawal"
    return withdrawal or deposit, "Withdrawal" if withdrawal else "Deposit"


def _expected_component(settlement, component):
    if component == "Gross":
        return flt(settlement.gross_amount, 2), "Deposit"
    if component == "Commission":
        return flt(settlement.commission_amount, 2), "Withdrawal"
    return flt(settlement.vat_amount, 2), "Withdrawal"


def _finalize_settlement(doc, tolerance):
    totals = {"Gross": 0.0, "Commission": 0.0, "VAT": 0.0}
    directions = defaultdict(list)
    for row in doc.statement_matches:
        totals[row.component] += flt(row.statement_amount, 2)
        directions[row.component].append(row.direction)

    doc.statement_gross_amount = flt(totals["Gross"], 2)
    doc.statement_commission_amount = flt(totals["Commission"], 2)
    doc.statement_vat_amount = flt(totals["VAT"], 2)
    doc.statement_net_amount = flt(
        doc.statement_gross_amount
        - doc.statement_commission_amount
        - doc.statement_vat_amount,
        2,
    )

    doc.gross_difference = flt(doc.statement_gross_amount - doc.gross_amount, 2)
    doc.commission_difference = flt(doc.statement_commission_amount - doc.commission_amount, 2)
    doc.vat_difference = flt(doc.statement_vat_amount - doc.vat_amount, 2)
    doc.net_difference = flt(doc.statement_net_amount - doc.expected_net, 2)

    required = []
    for component in ("Gross", "Commission", "VAT"):
        expected, expected_direction = _expected_component(doc, component)
        if abs(expected) <= tolerance:
            continue
        required.append(component)
        component_rows = [row for row in doc.statement_matches if row.component == component]
        component_ok = (
            bool(component_rows)
            and abs(totals[component] - expected) <= tolerance
            and all(row.direction == expected_direction for row in component_rows)
        )
        for row in component_rows:
            row.match_status = "Matched" if component_ok else "Difference"

    missing = [
        component
        for component in required
        if not any(row.component == component for row in doc.statement_matches)
    ]
    differences = any(
        abs(value) > tolerance
        for value in [
            doc.gross_difference,
            doc.commission_difference,
            doc.vat_difference,
            doc.net_difference,
        ]
    )

    if not doc.statement_matches:
        doc.status = "ERP Settlement Only"
    elif missing:
        doc.status = "Partial"
    elif differences:
        doc.status = "Amount Difference"
    else:
        direction_problem = any(
            row.match_status == "Difference" for row in doc.statement_matches
        )
        doc.status = "Amount Difference" if direction_problem else "Fully Reconciled"

    doc.save(ignore_permissions=True)


def execute_statement_reconciliation(run_doc):
    run_doc.check_permission("write")
    from_date = getdate(run_doc.from_date)
    to_date = getdate(run_doc.to_date)
    tolerance = abs(flt(run_doc.tolerance or 0.01, 2))

    settings = frappe.get_single(SETTINGS_DOCTYPE)
    terminal_ref_length = settings.get("bank_statement_terminal_reference_length") or 8
    mappings = _mapping_rows()
    if not mappings:
        frappe.throw(
            _(
                "Configure POS Reconciliation Settings > Bank Statement Code Mappings before running statement reconciliation."
            )
        )

    groups, source_exception_count = _source_groups(
        run_doc.bank_account,
        from_date,
        to_date,
        terminal_ref_length,
    )

    settlements = {}
    for key, rows in groups.items():
        doc = _load_or_create_settlement(
            run_doc.name,
            run_doc.bank_account,
            key,
            rows,
        )
        settlements[
            (
                normalize_settlement_number(doc.settlement_number),
                normalize_terminal_reference(doc.bank_terminal_reference),
                cstr(doc.card_type).strip().upper(),
            )
        ] = doc

    statement_rows = _statement_rows(run_doc.bank_account, from_date, to_date)
    parsed_count = 0
    matched_line_count = 0
    unmatched_pos_count = 0

    for row in statement_rows:
        parsed = parse_pos_statement_text(_statement_text(row), mappings=mappings)
        if not parsed:
            continue

        parsed_count += 1
        key = (
            parsed.settlement_number,
            parsed.bank_terminal_reference,
            parsed.card_type,
        )
        settlement = settlements.get(key)
        if not settlement:
            unmatched_pos_count += 1
            continue

        amount, direction = _component_amount(row, parsed.component)
        expected, expected_direction = _expected_component(settlement, parsed.component)
        line_status = (
            "Matched"
            if abs(amount - expected) <= tolerance and direction == expected_direction
            else "Difference"
        )
        settlement.append(
            "statement_matches",
            {
                "bank_transaction": row.name,
                "transaction_date": row.date,
                "component": parsed.component,
                "direction": direction,
                "statement_amount": amount,
                "reference_number": row.reference_number,
                "description": row.description,
                "match_status": line_status,
            },
        )
        matched_line_count += 1

    for settlement in settlements.values():
        _finalize_settlement(settlement, tolerance)

    fully_reconciled = sum(
        1 for doc in settlements.values() if doc.status == "Fully Reconciled"
    )
    exception_settlements = len(settlements) - fully_reconciled
    statement_deposit_total = flt(sum(flt(row.deposit, 2) for row in statement_rows), 2)
    statement_withdrawal_total = flt(sum(flt(row.withdrawal, 2) for row in statement_rows), 2)
    other_statement_lines = max(len(statement_rows) - parsed_count, 0)

    result = {
        "settlement_count": len(settlements),
        "fully_reconciled_settlements": fully_reconciled,
        "exception_settlements": exception_settlements,
        "source_exception_count": source_exception_count,
        "statement_line_count": len(statement_rows),
        "parsed_pos_statement_lines": parsed_count,
        "matched_pos_statement_lines": matched_line_count,
        "unmatched_pos_statement_lines": unmatched_pos_count,
        "other_statement_lines": other_statement_lines,
        "statement_deposit_total": statement_deposit_total,
        "statement_withdrawal_total": statement_withdrawal_total,
        "status": "Completed",
        "last_run_on": now_datetime(),
    }

    frappe.db.set_value(
        "POS Bank Statement Reconciliation",
        run_doc.name,
        result,
        update_modified=True,
    )
    frappe.clear_cache()
    return result
