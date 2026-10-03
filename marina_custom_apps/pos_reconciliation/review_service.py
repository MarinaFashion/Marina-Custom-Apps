from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import AlhamraniAdapter

RECONCILIATION_RECORD = "POS Reconciliation Record"
DEFAULT_PAGE_LENGTH = 25
MAX_PAGE_LENGTH = 100

RESULT_STATUS_FILTERS = {
    "Matching": {"match_status": "Matching"},
    "Discrepancy": {"match_status": "Discrepancy"},
    "Bank Pending": {"match_status": "Bank Only", "resolution_status": "Pending"},
    "Marina Pending": {"match_status": "Alhamrani Only", "resolution_status": "Pending"},
    "Manually Cleared": {"resolution_status": "Manually Cleared"},
    "All Pending": {"resolution_status": "Pending"},
    # Backward-compatible internal aliases. These are no longer shown as the
    # primary Finance review pills but existing links/API calls remain valid.
    "Bank Only": {"match_status": "Bank Only"},
    "Alhamrani Only": {"match_status": "Alhamrani Only"},
    "Pending": {"resolution_status": "Pending"},
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
            "name", "transaction_date", "terminal_id", "pos_profile", "card_type",
            "match_status", "resolution_status", "alhamrani_duplicate_count", ref_field,
        ],
        order_by="transaction_date desc, name desc",
        start=start,
        page_length=page_length,
    )
    total = _count_records(filters, or_filters)

    rows = _bank_rows_for_refs(refs) if source == "bank" else _alhamrani_rows_for_refs(refs)
    return {"source": source, "rows": rows, "total": total, "start": start, "page_length": page_length}


def get_results_page(
    run_name,
    status="All",
    start=0,
    page_length=DEFAULT_PAGE_LENGTH,
    search=None,
    from_date=None,
    to_date=None,
    settlement_number=None,
    settlement_date=None,
    pos_profile=None,
    terminal_id=None,
    card_type=None,
    finance_review_status=None,
    before_integration=None,
):
    run = _get_run(run_name)
    start, page_length = _page_args(start, page_length)

    status = cstr(status).strip() or "All"
    filters = {"run": run.name}
    filters.update(RESULT_STATUS_FILTERS.get(status, {}))

    from_date = getdate(from_date) if from_date else None
    to_date = getdate(to_date) if to_date else None
    if from_date and to_date and from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date."))
    if from_date and to_date:
        filters["transaction_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["transaction_date"] = [">=", from_date]
    elif to_date:
        filters["transaction_date"] = ["<=", to_date]

    values = {
        "settlement_number": settlement_number,
        "settlement_date": settlement_date,
        "pos_profile": pos_profile,
        "terminal_id": terminal_id,
        "card_type": card_type,
        "finance_review_status": finance_review_status,
    }
    for fieldname, value in values.items():
        value = cstr(value).strip()
        if value:
            filters[fieldname] = value

    if before_integration not in (None, "", "All"):
        filters["before_integration"] = cint(before_integration)

    or_filters = _result_search_filters(search)
    fields = [
        "name", "transaction_date", "pos_profile", "terminal_id", "card_type",
        "bank_transaction", "alhamrani_transaction", "match_status", "resolution_status",
        "before_integration", "settlement_number", "settlement_date", "pos_reconciliation_number",
        "finance_review_status", "finance_reviewed_by", "finance_reviewed_on", "finance_review_note",
        "pan_validation_method", "discrepancy_fields", "bank_amount", "alhamrani_amount",
        "amount_difference", "bank_commission_amount", "bank_commission_vat_amount",
        "bank_settlement_amount", "manual_clearance_reason",
    ]
    rows = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        order_by="transaction_date desc, name desc",
        start=start,
        page_length=page_length,
    )
    total = _count_records(filters, or_filters)

    settlement_summary = None
    if status in {"Bank Pending", "Bank Only"} and cstr(settlement_number).strip():
        settlement_summary = _settlement_summary(filters, or_filters)

    return {
        "status": status,
        "rows": [dict(row) for row in rows],
        "total": total,
        "start": start,
        "page_length": page_length,
        "settlement_summary": settlement_summary,
    }


def get_result_filter_options(run_name, status="Bank Pending"):
    run = _get_run(run_name)
    status = cstr(status).strip() or "Bank Pending"
    extra = RESULT_STATUS_FILTERS.get(status, {})

    where = ["run = %(run)s"]
    params = {"run": run.name}
    for fieldname, value in extra.items():
        where.append(f"`{fieldname}` = %({fieldname})s")
        params[fieldname] = value
    where_sql = " AND ".join(where)

    def distinct(fieldname):
        return [
            row[0]
            for row in frappe.db.sql(
                f"""
                SELECT DISTINCT `{fieldname}`
                FROM `tabPOS Reconciliation Record`
                WHERE {where_sql}
                  AND `{fieldname}` IS NOT NULL
                  AND `{fieldname}` != ''
                ORDER BY `{fieldname}`
                """,
                params,
                as_list=True,
            )
        ]

    return {
        "settlement_numbers": distinct("settlement_number"),
        "pos_profiles": distinct("pos_profile"),
        "terminal_ids": distinct("terminal_id"),
        "card_types": distinct("card_type"),
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


def _settlement_summary(filters, or_filters=None):
    refs = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "bank_amount", "bank_commission_amount", "bank_commission_vat_amount",
            "bank_settlement_amount", "finance_review_status", "settlement_number",
            "settlement_date", "terminal_id", "pos_profile",
        ],
        limit_page_length=0,
    )

    gross = sum(flt(row.bank_amount, 2) for row in refs)
    commission = sum(flt(row.bank_commission_amount, 2) for row in refs)
    vat = sum(flt(row.bank_commission_vat_amount, 2) for row in refs)
    bank_settlement = sum(flt(row.bank_settlement_amount, 2) for row in refs)

    statuses = {"Checked & Approved": 0, "Needs Investigation": 0, "Pending Review": 0}
    for row in refs:
        review_status = cstr(row.finance_review_status).strip() or "Pending Review"
        if review_status in statuses:
            statuses[review_status] += 1

    settlement_dates = {cstr(row.settlement_date) for row in refs if row.settlement_date}
    terminals = {cstr(row.terminal_id) for row in refs if row.terminal_id}
    profiles = {cstr(row.pos_profile) for row in refs if row.pos_profile}

    return {
        "transaction_count": len(refs),
        "gross_amount": flt(gross, 2),
        "commission": flt(commission, 2),
        "vat": flt(vat, 2),
        "expected_net": flt(gross - commission - vat, 2),
        "bank_settlement_amount": flt(bank_settlement, 2),
        "approved_count": statuses["Checked & Approved"],
        "investigation_count": statuses["Needs Investigation"],
        "pending_review_count": statuses["Pending Review"],
        "settlement_date_count": len(settlement_dates),
        "terminal_count": len(terminals),
        "pos_profile_count": len(profiles),
    }


def _like(value):
    return ["like", f"%{cstr(value).strip()}%"]


def _source_search_filters(source, search):
    search = cstr(search).strip()
    if not search:
        return None
    ref_field = "bank_transaction" if source == "bank" else "alhamrani_transaction"
    return {
        ref_field: _like(search), "terminal_id": _like(search), "pos_profile": _like(search),
        "card_type": _like(search), "match_status": _like(search), "resolution_status": _like(search),
    }


def _result_search_filters(search):
    search = cstr(search).strip()
    if not search:
        return None
    return {
        "name": _like(search), "bank_transaction": _like(search), "alhamrani_transaction": _like(search),
        "terminal_id": _like(search), "pos_profile": _like(search), "card_type": _like(search),
        "settlement_number": _like(search), "match_status": _like(search),
        "resolution_status": _like(search), "finance_review_status": _like(search),
        "finance_review_note": _like(search), "discrepancy_fields": _like(search),
    }


def _bank_rows_for_refs(refs):
    names = [row.bank_transaction for row in refs if row.bank_transaction]
    if not names:
        return []

    source_rows = frappe.get_all(
        "Bank POS Transaction",
        filters={"name": ["in", names]},
        fields=[
            "name", "transaction_date", "transaction_time", "terminal_id", "rrn", "auth_code",
            "transaction_type", "transaction_amount", "card_type", "pos_profile",
        ],
        limit_page_length=0,
    )
    source_map = {row.name: row for row in source_rows}
    output = []
    for ref in refs:
        row = source_map.get(ref.bank_transaction)
        if not row:
            continue
        output.append({
            "name": row.name, "transaction_date": row.transaction_date,
            "transaction_time": cstr(row.transaction_time), "terminal_id": row.terminal_id,
            "rrn": row.rrn, "auth_code": row.auth_code, "transaction_type": row.transaction_type,
            "amount": flt(row.transaction_amount, 2), "card_type": row.card_type,
            "pos_profile": row.pos_profile, "match_status": ref.match_status,
            "resolution_status": ref.resolution_status,
        })
    return output


def _alhamrani_rows_for_refs(refs):
    names = [row.alhamrani_transaction for row in refs if row.alhamrani_transaction]
    if not names:
        return []

    adapter = AlhamraniAdapter()
    source_map = {}
    for raw in adapter.get_rows_by_names(names):
        normalized = adapter.normalized_row(raw)
        source_map[normalized.name] = normalized

    output = []
    for ref in refs:
        row = source_map.get(ref.alhamrani_transaction)
        if not row:
            continue
        output.append({
            "name": row.name, "transaction_date": row.transaction_date,
            "transaction_time": cstr(row.transaction_time), "terminal_id": row.terminal_id,
            "rrn": row.rrn, "auth_code": row.auth_code, "transaction_type": row.transaction_type,
            "amount": flt(row.amount, 2) if row.amount is not None else 0.0,
            "card_type": row.card_type, "pos_profile": ref.pos_profile or row.source_pos_profile,
            "match_status": ref.match_status, "resolution_status": ref.resolution_status,
            "duplicate_count": cint(ref.alhamrani_duplicate_count),
        })
    return output
