from __future__ import annotations

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import AlhamraniAdapter

RECONCILIATION_RECORD = "POS Reconciliation Record"
DEFAULT_PAGE_LENGTH = 25
MAX_PAGE_LENGTH = 100

RESULT_STATUS_FILTERS = {
    "Fully Matching": {"match_status": "Fully Matching"},
    "Matching Not Settled": {"match_status": "Matching Not Settled"},
    "Bank Only - Settled": {"match_status": "Bank Only - Settled"},
    "Bank Only - Not Settled": {"match_status": "Bank Only - Not Settled"},
    "Alhamrani Only": {"match_status": "Alhamrani Only"},
    "Discrepancy": {"match_status": "Discrepancy"},
    "All Pending": {"resolution_status": "Pending"},
    # Backward-compatible aliases for earlier experimental links/API calls.
    "Matching": {"match_status": ["in", ["Fully Matching", "Matching Not Settled", "Matching"]]},
    "Bank Pending": {
        "match_status": ["in", ["Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"]],
        "resolution_status": "Pending",
    },
    "Bank Only": {"match_status": ["in", ["Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"]]},
    "Marina Pending": {"match_status": "Alhamrani Only", "resolution_status": "Pending"},
    "Pending": {"resolution_status": "Pending"},
}

LEDGER_POSTING_STATUS_FILTERS = {
    "Posted to Ledger": ["Posted", "Posted - Review Required"],
    "Unposted to Ledger": ["Pending Accounting", "Draft Created", "Draft - Review Required"],
    "No Posting Required": ["No Charges"],
    "Not Eligible": ["Not Eligible"],
}

ACCOUNTING_ELIGIBLE_STATUSES = {
    "Pending Accounting",
    "Draft Created",
    "Draft - Review Required",
    "Posted",
    "Posted - Review Required",
    "No Charges",
}


def multi_filter_values(value):
    """Return a clean list for UI filters that may submit one or many values."""
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            raw = parsed if isinstance(parsed, list) else [text]
        else:
            raw = [text]
    else:
        raw = [value]

    output = []
    seen = set()
    for item in raw:
        item = cstr(item).strip()
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _apply_multi_filter(filters, fieldname, value):
    values = multi_filter_values(value)
    if not values:
        return
    filters[fieldname] = values[0] if len(values) == 1 else ["in", values]


def _settlement_sort_key(value):
    text = cstr(value).strip()
    if text.isdigit():
        return (0, int(text), text)
    match = re.match(r"^\s*(\d+)", text)
    if match:
        return (0, int(match.group(1)), text.casefold())
    return (1, text.casefold(), text)


def apply_accounting_filters(filters, accounting_status=None, ledger_posting_status=None):
    accounting_status = cstr(accounting_status).strip()
    ledger_posting_status = cstr(ledger_posting_status).strip()

    allowed_statuses = None
    if ledger_posting_status:
        allowed_statuses = LEDGER_POSTING_STATUS_FILTERS.get(ledger_posting_status)
        if not allowed_statuses:
            frappe.throw(_("Invalid Ledger Posting Status."))

    if accounting_status and allowed_statuses is not None:
        if accounting_status not in allowed_statuses:
            filters["accounting_status"] = "__NO_MATCH__"
        else:
            filters["accounting_status"] = accounting_status
    elif accounting_status:
        filters["accounting_status"] = accounting_status
    elif allowed_statuses is not None:
        filters["accounting_status"] = ["in", allowed_statuses]

    return filters


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


def _apply_response_meaning_filter(filters, response_meaning):
    """Filter existing reconciliation rows by their original Alhamrani response meaning.

    No rerun or mutation of reconciled/posted records is needed.
    """
    value = cstr(response_meaning).strip()
    if not value:
        return
    from marina_custom_apps.pos_reconciliation.alhamrani_adapter import ALHAMRANI_DOCTYPE
    if not frappe.get_meta(ALHAMRANI_DOCTYPE).has_field("response_meaning"):
        frappe.throw(_("Alhamrani Transaction does not expose Response Meaning."))
    source_names = frappe.get_all(ALHAMRANI_DOCTYPE,
        filters={"response_meaning": value}, pluck="name", limit_page_length=0)
    # Frappe's in-filter cannot be empty; an impossible name gives zero results.
    filters["alhamrani_transaction"] = ["in", source_names or ["__NO_ALHAMRANI_RESPONSE_MATCH__"]]


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
    
    bank_statement_status=None,
    accounting_status=None,
    ledger_posting_status=None,
    before_integration=None,
    response_meaning=None,
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

    _apply_multi_filter(filters, "settlement_number", settlement_number)
    _apply_multi_filter(filters, "pos_profile", pos_profile)
    _apply_multi_filter(filters, "terminal_id", terminal_id)

    values = {
        "settlement_date": settlement_date,
        "card_type": card_type,
        
    }
    for fieldname, value in values.items():
        value = cstr(value).strip()
        if value:
            filters[fieldname] = value

    apply_accounting_filters(
        filters,
        accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,
    )

    if before_integration not in (None, "", "All"):
        filters["before_integration"] = cint(before_integration)

    _apply_response_meaning_filter(filters, response_meaning)
    or_filters = _result_search_filters(search)
    fields = [
        "name", "transaction_date", "pos_profile", "terminal_id", "card_type",
        "bank_transaction", "alhamrani_transaction", "match_status", "resolution_status",
        "before_integration", "settlement_number", "settlement_date", "pos_reconciliation_number",
        "bank_statement_status", "bank_statement_reconciliation", "bank_statement_settlement",
        "bank_statement_references", "bank_statement_checked_on",
        "pan_validation_method", "discrepancy_fields", "bank_amount", "alhamrani_amount",
        "amount_difference", "bank_commission_amount", "bank_commission_vat_amount",
        "bank_settlement_amount", "accounting_status", "accounting_posting", "journal_entry",
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

    filtered_summary = _filtered_summary(filters, or_filters)

    return {
        "status": status,
        "rows": [dict(row) for row in rows],
        "total": total,
        "start": start,
        "page_length": page_length,
        "filtered_summary": filtered_summary,
        # Backward-compatible alias used by Finance review actions.
        "settlement_summary": filtered_summary,
    }


def _facet_filters(
    run,status="All",from_date=None,to_date=None,settlement_number=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,bank_statement_status=None,
    accounting_status=None,ledger_posting_status=None,before_integration=None,response_meaning=None,exclude=None,
):
    exclude=set(exclude or [])
    filters={"run":run.name}
    if "status" not in exclude:
        filters.update(RESULT_STATUS_FILTERS.get(cstr(status).strip() or "All",{}))
    start=getdate(from_date) if from_date else None
    end=getdate(to_date) if to_date else None
    if start and end and start>end:
        frappe.throw(_("From Date cannot be after To Date."))
    if "transaction_date" not in exclude:
        if start and end: filters["transaction_date"]=["between",[start,end]]
        elif start: filters["transaction_date"]=[">=",start]
        elif end: filters["transaction_date"]=["<=",end]
    for fieldname, value in {
        "settlement_number": settlement_number,
        "pos_profile": pos_profile,
        "terminal_id": terminal_id,
    }.items():
        if fieldname not in exclude:
            _apply_multi_filter(filters, fieldname, value)

    for fieldname,value in {
        "settlement_date":settlement_date,"card_type":card_type,
    }.items():
        if fieldname in exclude: continue
        value=cstr(value).strip()
        if value: filters[fieldname]=value
    apply_accounting_filters(
        filters,
        accounting_status=None if "accounting_status" in exclude else accounting_status,
        ledger_posting_status=None if "ledger_posting_status" in exclude else ledger_posting_status,
    )
    if "before_integration" not in exclude and before_integration not in (None,"","All"):
        filters["before_integration"]=cint(before_integration)
    if "response_meaning" not in exclude:
        _apply_response_meaning_filter(filters, response_meaning)
    return filters


def _facet_values(fieldname,filters):
    rows=frappe.get_all(
        RECONCILIATION_RECORD,filters=filters,fields=[fieldname],group_by=fieldname,
        order_by=fieldname,limit_page_length=0,
    )
    return [row.get(fieldname) for row in rows if row.get(fieldname) not in (None,"")]


def _facet_status_counts(filters):
    rows=frappe.get_all(
        RECONCILIATION_RECORD,filters=filters,
        fields=["match_status","resolution_status","count(name) as total"],
        group_by="match_status, resolution_status",limit_page_length=0,
    )
    out={
        "All":0,
        "Fully Matching":0,
        "Matching Not Settled":0,
        "Bank Only - Settled":0,
        "Bank Only - Not Settled":0,
        "Alhamrani Only":0,
        "Discrepancy":0,
        "All Pending":0,
    }
    for row in rows:
        n=cint(row.total); m=cstr(row.match_status).strip(); r=cstr(row.resolution_status).strip()
        out["All"]+=n
        if m=="Fully Matching": out["Fully Matching"]+=n
        if m in {"Matching Not Settled", "Matching"}: out["Matching Not Settled"]+=n
        if m=="Bank Only - Settled": out["Bank Only - Settled"]+=n
        if m in {"Bank Only - Not Settled", "Bank Only"}: out["Bank Only - Not Settled"]+=n
        if m=="Alhamrani Only": out["Alhamrani Only"]+=n
        if m=="Discrepancy": out["Discrepancy"]+=n
        if r=="Pending": out["All Pending"]+=n
    return out


def get_result_filter_options(
    run_name,status="All",from_date=None,to_date=None,settlement_number=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,bank_statement_status=None,
    accounting_status=None,ledger_posting_status=None,before_integration=None,response_meaning=None,
):
    run=_get_run(run_name)
    values=dict(
        status=status,from_date=from_date,to_date=to_date,settlement_number=settlement_number,
        settlement_date=settlement_date,pos_profile=pos_profile,terminal_id=terminal_id,card_type=card_type,
        bank_statement_status=bank_statement_status,accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,before_integration=before_integration,response_meaning=response_meaning,
    )
    def f(*excluded): return _facet_filters(run,exclude=set(excluded),**values)

    accounting=_facet_values("accounting_status",f("accounting_status"))
    ledger_source=set(_facet_values("accounting_status",f("ledger_posting_status")))
    ledgers=[label for label,statuses in LEDGER_POSTING_STATUS_FILTERS.items() if ledger_source.intersection(statuses)]
    before=[str(cint(v)) for v in _facet_values("before_integration",f("before_integration"))]
    return {
        "settlement_numbers":sorted(_facet_values("settlement_number",f("settlement_number")), key=_settlement_sort_key),
        "pos_profiles":_facet_values("pos_profile",f("pos_profile")),
        "terminal_ids":_facet_values("terminal_id",f("terminal_id")),
        "card_types":_facet_values("card_type",f("card_type")),
        "accounting_statuses":accounting,
        "ledger_posting_statuses":ledgers,
        "before_integration_values":before,
        "status_counts":_facet_status_counts(f("status")),
    }

def _get_run(run_name):
    if run_name != "POS Reconciliation Run":
        frappe.throw(_("Invalid Single POS Reconciliation Control."))
    run = frappe.get_single("POS Reconciliation Run")
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


def _group_counts(fieldname, filters, or_filters=None):
    rows = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[fieldname, "count(name) as total"],
        group_by=fieldname,
        limit_page_length=0,
    )
    return {
        cstr(row.get(fieldname)).strip(): cint(row.total)
        for row in rows
        if cstr(row.get(fieldname)).strip()
    }


def _distinct_count(fieldname, filters, or_filters=None):
    rows = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[fieldname],
        group_by=fieldname,
        limit_page_length=0,
    )
    return sum(1 for row in rows if cstr(row.get(fieldname)).strip())


def _filtered_summary(filters, or_filters=None):
    totals = frappe.get_all(
        RECONCILIATION_RECORD,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "count(name) as transaction_count",
            "sum(bank_amount) as gross_amount",
            "sum(alhamrani_amount) as marina_amount",
            "sum(bank_commission_amount) as commission",
            "sum(bank_commission_vat_amount) as vat",
            "sum(bank_settlement_amount) as bank_settlement_amount",
            # Compute the outstanding-receipt proxy in the SAME aggregate
            # query as the other financial cards (no per-row Python scans).
            # A matched receipt already has both sources; count bank gross
            # once. Alhamrani-only has no bank row, so count its own amount.
            "sum(CASE "
            "WHEN match_status = 'Matching Not Settled' THEN COALESCE(bank_amount, 0) "
            "WHEN match_status = 'Alhamrani Only' THEN COALESCE(alhamrani_amount, 0) "
            "ELSE 0 END) as pending_bank_receipts",
        ],
        limit_page_length=1,
    )
    total = totals[0] if totals else frappe._dict()

    transaction_count = cint(total.get("transaction_count"))
    gross = flt(total.get("gross_amount"), 2)
    marina_amount = flt(total.get("marina_amount"), 2)
    commission = flt(total.get("commission"), 2)
    vat = flt(total.get("vat"), 2)
    bank_settlement = flt(total.get("bank_settlement_amount"), 2)
    pending_bank_receipts = flt(total.get("pending_bank_receipts"), 2)
    commission_pct = flt((commission / gross) * 100, 2) if gross else 0
    vat_pct = flt((vat / commission) * 100, 2) if commission else 0

    bank_statement = _group_counts("bank_statement_status", filters, or_filters)
    accounting = _group_counts("accounting_status", filters, or_filters)

    accounting_eligible = sum(
        accounting.get(status, 0)
        for status in ACCOUNTING_ELIGIBLE_STATUSES
    )
    draft_created = (
        accounting.get("Draft Created", 0)
        + accounting.get("Draft - Review Required", 0)
    )
    posted_to_ledger = (
        accounting.get("Posted", 0)
        + accounting.get("Posted - Review Required", 0)
    )

    return {
        "transaction_count": transaction_count,
        "gross_amount": gross,
        "marina_amount": marina_amount,
        "commission": commission,
        "commission_pct": commission_pct,
        "vat": vat,
        "vat_pct": vat_pct,
        "expected_net": flt(gross - commission - vat, 2),
        "bank_settlement_amount": bank_settlement,
        "pending_bank_receipts": pending_bank_receipts,
        "bank_statement_fully_reconciled_count": bank_statement.get("Fully Reconciled", 0),
        "bank_statement_found_count": bank_statement.get("Statement Found", 0),
        "bank_statement_exception_count": bank_statement.get("Exception", 0),
        "bank_statement_not_found_count": bank_statement.get("Not Found", 0),
        "bank_statement_not_checked_count": max(
            transaction_count
            - bank_statement.get("Fully Reconciled", 0)
            - bank_statement.get("Statement Found", 0)
            - bank_statement.get("Exception", 0)
            - bank_statement.get("Not Found", 0),
            0,
        ),
        "accounting_eligible_count": accounting_eligible,
        "pending_accounting_count": accounting.get("Pending Accounting", 0),
        "draft_created_count": draft_created,
        "posted_to_ledger_count": posted_to_ledger,
        "no_charges_count": accounting.get("No Charges", 0),
        "not_eligible_count": accounting.get("Not Eligible", 0),
        "settlement_date_count": _distinct_count("settlement_date", filters, or_filters),
        "terminal_count": _distinct_count("terminal_id", filters, or_filters),
        "pos_profile_count": _distinct_count("pos_profile", filters, or_filters),
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
        "resolution_status": _like(search), 
        "bank_statement_status": _like(search), "bank_statement_reconciliation": _like(search),
        "bank_statement_settlement": _like(search), "bank_statement_references": _like(search),
        "accounting_status": _like(search), "journal_entry": _like(search), "discrepancy_fields": _like(search),
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
