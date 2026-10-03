from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    ALHAMRANI_DOCTYPE,
    AlhamraniAdapter,
)

RECONCILIATION_RECORD = "POS Reconciliation Record"
DEFAULT_PAGE_LENGTH = 25
MAX_PAGE_LENGTH = 100

RESULT_STATUS_FILTERS = {
    "Matching": {"match_status": "Matching"},
    "Discrepancy": {"match_status": "Discrepancy"},
    "Bank Only": {"match_status": "Bank Only"},
    "Alhamrani Only": {"match_status": "Alhamrani Only"},
    "Pending": {"resolution_status": "Pending"},
    "Manually Cleared": {"resolution_status": "Manually Cleared"},
}


def get_source_page(run_name, source, start=0, page_length=DEFAULT_PAGE_LENGTH, search=None):
    run = _get_run(run_name)
    source = cstr(source).strip().lower()
    if source not in {"bank", "alhamrani"}:
        frappe.throw(_("Source must be Bank or Alhamrani."))

    start, page_length = _page_args(start, page_length)
    ref_field = "bank_transaction" if source == "bank" else "alhamrani_transaction"
    filters = {"run": run.name, ref_field: ["is", "set"]}
    or_filters = _source_search_filters(source, search)

    refs = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "transaction_date",
            "terminal_id",
            "pos_profile",
            "card_type",
            "match_status",
            "resolution_status",
            "alhamrani_duplicate_count",
            ref_field,
        ],
        order_by="transaction_date desc, name desc",
        start=start,
        page_length=page_length,
    )
    total = _count_records(filters, or_filters)

    if source == "bank":
        rows = _bank_rows_for_refs(refs)
    else:
        rows = _alhamrani_rows_for_refs(refs)

    return {
        "source": source,
        "rows": rows,
        "total": total,
        "start": start,
        "page_length": page_length,
    }


def get_results_page(
    run_name,
    status="All",
    start=0,
    page_length=DEFAULT_PAGE_LENGTH,
    search=None,
):
    run = _get_run(run_name)
    start, page_length = _page_args(start, page_length)

    status = cstr(status).strip() or "All"
    filters = {"run": run.name}
    filters.update(RESULT_STATUS_FILTERS.get(status, {}))
    or_filters = _result_search_filters(search)

    rows = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "transaction_date",
            "pos_profile",
            "terminal_id",
            "card_type",
            "bank_transaction",
            "alhamrani_transaction",
            "match_status",
            "resolution_status",
            "before_integration",
            "discrepancy_fields",
            "bank_amount",
            "alhamrani_amount",
            "amount_difference",
            "manual_clearance_reason",
        ],
        order_by="transaction_date desc, name desc",
        start=start,
        page_length=page_length,
    )
    total = _count_records(filters, or_filters)

    return {
        "status": status,
        "rows": [dict(row) for row in rows],
        "total": total,
        "start": start,
        "page_length": page_length,
    }


def _get_run(run_name):
    if not run_name:
        frappe.throw(_("Reconciliation Run is required."))
    run = frappe.get_doc("POS Reconciliation Run", run_name)
    run.check_permission("read")
    return run


def _page_args(start, page_length):
    start = max(cint(start), 0)
    page_length = cint(page_length) or DEFAULT_PAGE_LENGTH
    page_length = min(max(page_length, 10), MAX_PAGE_LENGTH)
    return start, page_length


def _count_records(filters, or_filters=None):
    rows = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=["count(name) as total"],
        limit_page_length=1,
    )
    return cint(rows[0].total) if rows else 0


def _like(value):
    return ["like", f"%{cstr(value).strip()}%"]


def _source_search_filters(source, search):
    search = cstr(search).strip()
    if not search:
        return None

    ref_field = "bank_transaction" if source == "bank" else "alhamrani_transaction"
    return {
        ref_field: _like(search),
        "terminal_id": _like(search),
        "pos_profile": _like(search),
        "card_type": _like(search),
        "match_status": _like(search),
        "resolution_status": _like(search),
    }


def _result_search_filters(search):
    search = cstr(search).strip()
    if not search:
        return None

    return {
        "name": _like(search),
        "bank_transaction": _like(search),
        "alhamrani_transaction": _like(search),
        "terminal_id": _like(search),
        "pos_profile": _like(search),
        "card_type": _like(search),
        "match_status": _like(search),
        "resolution_status": _like(search),
        "discrepancy_fields": _like(search),
    }


def _bank_rows_for_refs(refs):
    names = [row.bank_transaction for row in refs if row.bank_transaction]
    if not names:
        return []

    source_rows = frappe.get_all(
        "Bank POS Transaction",
        filters={"name": ["in", names]},
        fields=[
            "name",
            "transaction_date",
            "transaction_time",
            "terminal_id",
            "rrn",
            "auth_code",
            "transaction_type",
            "transaction_amount",
            "card_type",
            "pos_profile",
        ],
        limit_page_length=0,
    )
    source_map = {row.name: row for row in source_rows}

    output = []
    for ref in refs:
        row = source_map.get(ref.bank_transaction)
        if not row:
            continue
        output.append(
            {
                "name": row.name,
                "transaction_date": row.transaction_date,
                "transaction_time": cstr(row.transaction_time),
                "terminal_id": row.terminal_id,
                "rrn": row.rrn,
                "auth_code": row.auth_code,
                "transaction_type": row.transaction_type,
                "amount": flt(row.transaction_amount, 2),
                "card_type": row.card_type,
                "pos_profile": row.pos_profile,
                "match_status": ref.match_status,
                "resolution_status": ref.resolution_status,
            }
        )
    return output


def _alhamrani_rows_for_refs(refs):
    names = [row.alhamrani_transaction for row in refs if row.alhamrani_transaction]
    if not names:
        return []

    adapter = AlhamraniAdapter()
    raw_rows = adapter.get_rows_by_names(names)
    source_map = {}
    for raw in raw_rows:
        normalized = adapter.normalized_row(raw)
        source_map[normalized.name] = normalized

    output = []
    for ref in refs:
        row = source_map.get(ref.alhamrani_transaction)
        if not row:
            continue
        output.append(
            {
                "name": row.name,
                "transaction_date": row.transaction_date,
                "transaction_time": cstr(row.transaction_time),
                "terminal_id": row.terminal_id,
                "rrn": row.rrn,
                "auth_code": row.auth_code,
                "transaction_type": row.transaction_type,
                "amount": flt(row.amount, 2) if row.amount is not None else 0.0,
                "card_type": row.card_type,
                "pos_profile": ref.pos_profile or row.source_pos_profile,
                "match_status": ref.match_status,
                "resolution_status": ref.resolution_status,
                "duplicate_count": cint(ref.alhamrani_duplicate_count),
            }
        )
    return output
