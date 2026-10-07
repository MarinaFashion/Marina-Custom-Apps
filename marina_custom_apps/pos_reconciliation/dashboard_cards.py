from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cstr, flt
from frappe.utils.caching import redis_cache

from marina_custom_apps.pos_reconciliation.card_type_mapping import get_card_type_mapper

RECONCILIATION_RECORD = "POS Reconciliation Record"
BANK_TRANSACTION = "Bank POS Transaction"

STATUS_CARD_DEFINITIONS = [
    ("POS Reconciliation - Total Records", "Total Records", "get_total_records_card", RECONCILIATION_RECORD),
    ("POS Reconciliation - Cleared Records", "Cleared Records", "get_cleared_records_card", RECONCILIATION_RECORD),
    ("POS Reconciliation - Pending Exceptions", "Pending Exceptions", "get_pending_exceptions_card", RECONCILIATION_RECORD),
    ("POS Reconciliation - Manually Cleared", "Manually Cleared", "get_manual_cleared_card", RECONCILIATION_RECORD),
    ("POS Reconciliation - Match Percent", "Match %", "get_match_percent_card", RECONCILIATION_RECORD),
]

FINANCIAL_CARD_DEFINITIONS = [
    ("POS Reconciliation - Total Bank Amount", "Total Bank Amount", "get_total_amount_card", BANK_TRANSACTION, "SAR"),
    ("POS Reconciliation - Commission", "Commission", "get_total_commission_card", BANK_TRANSACTION, "SAR"),
    ("POS Reconciliation - Commission Percent", "Commission %", "get_commission_percent_card", BANK_TRANSACTION, None),
    ("POS Reconciliation - Commission VAT", "VAT on Commission", "get_commission_vat_card", BANK_TRANSACTION, "SAR"),
]

LEGACY_CARD_TYPE_CARDS = [
    "POS Reconciliation - Mada Amount",
    "POS Reconciliation - Visa Amount",
    "POS Reconciliation - Mastercard Amount",
]

ALL_CARD_NAMES = [row[0] for row in STATUS_CARD_DEFINITIONS] + [row[0] for row in FINANCIAL_CARD_DEFINITIONS]


def number_card_documents():
    docs = []
    for name, label, method_name, document_type in STATUS_CARD_DEFINITIONS:
        docs.append(_number_card_doc(name, label, method_name, document_type))
    for name, label, method_name, document_type, currency in FINANCIAL_CARD_DEFINITIONS:
        docs.append(_number_card_doc(name, label, method_name, document_type, currency=currency))
    return docs


def _number_card_doc(name, label, method_name, document_type, currency=None):
    return {
        "doctype": "Number Card",
        "name": name,
        "label": label,
        "type": "Custom",
        "method": f"marina_custom_apps.pos_reconciliation.dashboard_cards.{method_name}",
        "document_type": document_type,
        "is_public": 1,
        "is_standard": 1,
        "module": "POS Reconciliation",
        "filters_json": "[]",
        "dynamic_filters_json": "[]",
        "show_percentage_stats": 0,
        "show_full_number": 1 if document_type == RECONCILIATION_RECORD else 0,
        "currency": currency or "",
    }


def _check_read_permission(doctype):
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(_("Not permitted to read {0}.").format(doctype), frappe.PermissionError)


def _result(value, fieldtype, route=None, route_options=None):
    result = {"value": value, "fieldtype": fieldtype}
    if route:
        result["route"] = route
    if route_options:
        result["route_options"] = route_options
    return result


def _record_route(**filters):
    options = {key: value for key, value in filters.items() if value not in (None, "")}
    return ["List", RECONCILIATION_RECORD], options or None


def _bank_route():
    return ["List", BANK_TRANSACTION], {"transaction_status": "Approved"}


def _current_reconciliation_cte():
    """SQL CTE for one current row per Bank/Alhamrani source transaction.

    Reconciliation Records are run-specific, so rerunning overlapping periods can create
    multiple historical rows for the same source transaction. The dashboard must count
    all source transactions once, not all historical run snapshots.
    """
    return """
        with ranked_bank as (
            select
                r.*,
                row_number() over (
                    partition by r.bank_transaction
                    order by
                        coalesce(r.last_reconciled_on, r.modified) desc,
                        r.modified desc,
                        r.name desc
                ) as source_rank
            from `tabPOS Reconciliation Record` r
            where coalesce(r.bank_transaction, '') <> ''
        ),
        ranked_alhamrani_only as (
            select
                r.*,
                row_number() over (
                    partition by r.alhamrani_transaction
                    order by
                        coalesce(r.last_reconciled_on, r.modified) desc,
                        r.modified desc,
                        r.name desc
                ) as source_rank
            from `tabPOS Reconciliation Record` r
            where coalesce(r.bank_transaction, '') = ''
              and coalesce(r.alhamrani_transaction, '') <> ''
              and not exists (
                  select 1
                  from `tabPOS Reconciliation Record` matched
                  where matched.alhamrani_transaction = r.alhamrani_transaction
                    and coalesce(matched.bank_transaction, '') <> ''
              )
        ),
        current_records as (
            select * from ranked_bank where source_rank = 1
            union all
            select * from ranked_alhamrani_only where source_rank = 1
        )
    """


def _reconciliation_status_summary():
    _check_read_permission(RECONCILIATION_RECORD)
    return _cached_reconciliation_status_summary()


@redis_cache(ttl=30)
def _cached_reconciliation_status_summary():
    rows = frappe.db.sql(
        f"""
        {_current_reconciliation_cte()}
        select
            count(*) as total_records,
            sum(case when resolution_status in ('Auto Cleared', 'Manually Cleared') then 1 else 0 end) as cleared_records,
            sum(case when resolution_status = 'Pending' then 1 else 0 end) as pending_records,
            sum(case when resolution_status = 'Manually Cleared' then 1 else 0 end) as manually_cleared_records,
            sum(case when match_status = 'Matching' then 1 else 0 end) as matching_records
        from current_records
        """,
        as_dict=True,
    )
    row = frappe._dict(rows[0] if rows else {})
    return frappe._dict(
        total_records=int(row.total_records or 0),
        cleared_records=int(row.cleared_records or 0),
        pending_records=int(row.pending_records or 0),
        manually_cleared_records=int(row.manually_cleared_records or 0),
        matching_records=int(row.matching_records or 0),
    )


def _all_bank_summary(requested_card_type=None):
    """Aggregate all Approved Bank POS Transactions, independent of reconciliation runs."""
    _check_read_permission(BANK_TRANSACTION)
    return _cached_all_bank_summary(requested_card_type)


@redis_cache(ttl=30)
def _cached_all_bank_summary(requested_card_type=None):
    mapper = get_card_type_mapper()
    requested = mapper.resolve(requested_card_type) if requested_card_type else None
    conditions = ["upper(coalesce(transaction_status, '')) = 'APPROVED'"]
    params = {}
    if requested:
        raw_values = tuple(value.upper() for value in mapper.bank_source_values(requested))
        conditions.append("upper(coalesce(card_type, '')) in %(card_types)s")
        params["card_types"] = raw_values
    row = frappe.db.sql(
        f"""
        select
            coalesce(sum(transaction_amount), 0) as amount,
            coalesce(sum(fee_amount), 0) as commission,
            coalesce(sum(vat_amount), 0) as vat
        from `tabBank POS Transaction`
        where {' and '.join(conditions)}
        """,
        params,
        as_dict=True,
    )[0]
    return frappe._dict(
        amount=flt(row.amount, 2),
        commission=flt(row.commission, 2),
        vat=flt(row.vat, 2),
    )


def get_reconciliation_card_type_summary():
    """Group all unique reconciliation transactions by unified card type."""
    _check_read_permission(RECONCILIATION_RECORD)
    return _cached_reconciliation_card_type_summary()


@redis_cache(ttl=30)
def _cached_reconciliation_card_type_summary():
    """Bank-linked rows use Bank amount; true Alhamrani-only rows use Alhamrani amount."""
    raw_rows = frappe.db.sql(
        f"""
        {_current_reconciliation_cte()}
        select
            coalesce(nullif(card_type, ''), 'UNKNOWN') as card_type,
            count(*) as transaction_count,
            coalesce(sum(
                case
                    when coalesce(bank_transaction, '') <> '' then coalesce(bank_amount, 0)
                    else coalesce(alhamrani_amount, 0)
                end
            ), 0) as amount
        from current_records
        group by coalesce(nullif(card_type, ''), 'UNKNOWN')
        order by amount desc, card_type asc
        """,
        as_dict=True,
    )

    mapper = get_card_type_mapper()
    grouped = defaultdict(lambda: {"transaction_count": 0, "amount": 0.0})
    for row in raw_rows:
        normalized = mapper.resolve(row.card_type) if row.card_type != "UNKNOWN" else "UNKNOWN"
        normalized = normalized or "UNKNOWN"
        grouped[normalized]["transaction_count"] += int(row.transaction_count or 0)
        grouped[normalized]["amount"] += flt(row.amount, 2)

    return [
        frappe._dict(card_type=card_type, transaction_count=values["transaction_count"], amount=flt(values["amount"], 2))
        for card_type, values in sorted(grouped.items(), key=lambda item: (-flt(item[1]["amount"]), item[0]))
    ]


def display_card_type(value):
    token = cstr(value).strip().upper()
    labels = {
        "MADA": "Mada",
        "SPAN": "Mada",
        "VISA": "Visa",
        "MASTERCARD": "Mastercard",
        "MASTER CARD": "Mastercard",
        "MASTER_CARD": "Mastercard",
        "GCCCARD": "GCC Card",
        "GCC CARD": "GCC Card",
        "AMEX": "American Express",
        "UNKNOWN": _("Unknown"),
    }
    return labels.get(token, cstr(value).strip() or _("Unknown"))


@frappe.whitelist()
def get_total_records_card(filters=None):
    summary = _reconciliation_status_summary()
    route, options = _record_route()
    return _result(summary.total_records, "Int", route, options)


@frappe.whitelist()
def get_cleared_records_card(filters=None):
    summary = _reconciliation_status_summary()
    route, options = _record_route(resolution_status=["in", ["Auto Cleared", "Manually Cleared"]])
    return _result(summary.cleared_records, "Int", route, options)


@frappe.whitelist()
def get_pending_exceptions_card(filters=None):
    summary = _reconciliation_status_summary()
    route, options = _record_route(resolution_status="Pending")
    return _result(summary.pending_records, "Int", route, options)


@frappe.whitelist()
def get_manual_cleared_card(filters=None):
    summary = _reconciliation_status_summary()
    route, options = _record_route(resolution_status="Manually Cleared")
    return _result(summary.manually_cleared_records, "Int", route, options)


@frappe.whitelist()
def get_match_percent_card(filters=None):
    summary = _reconciliation_status_summary()
    value = summary.matching_records / summary.total_records * 100 if summary.total_records else 0.0
    route, options = _record_route(match_status="Matching")
    return _result(flt(value, 2), "Percent", route, options)


@frappe.whitelist()
def get_total_amount_card(filters=None):
    summary = _all_bank_summary()
    route, options = _bank_route()
    return _result(summary.amount, "Currency", route, options)


@frappe.whitelist()
def get_total_commission_card(filters=None):
    summary = _all_bank_summary()
    route, options = _bank_route()
    return _result(summary.commission, "Currency", route, options)


@frappe.whitelist()
def get_commission_percent_card(filters=None):
    summary = _all_bank_summary()
    value = summary.commission / summary.amount * 100 if summary.amount else 0.0
    route, options = _bank_route()
    return _result(flt(value, 4), "Percent", route, options)


@frappe.whitelist()
def get_commission_vat_card(filters=None):
    summary = _all_bank_summary()
    route, options = _bank_route()
    return _result(summary.vat, "Currency", route, options)


# Compatibility methods for the three old card-type Number Card documents.
def _card_amount(card_type):
    summary = _all_bank_summary(card_type)
    route, options = _bank_route()
    return _result(summary.amount, "Currency", route, options)


@frappe.whitelist()
def get_mada_amount_card(filters=None):
    return _card_amount("MADA")


@frappe.whitelist()
def get_visa_amount_card(filters=None):
    return _card_amount("VISA")


@frappe.whitelist()
def get_mastercard_amount_card(filters=None):
    return _card_amount("MASTERCARD")
