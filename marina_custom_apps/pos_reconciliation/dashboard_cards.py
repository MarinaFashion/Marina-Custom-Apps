from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr, flt

from marina_custom_apps.pos_reconciliation.reconciliation_engine import normalize_card_type

STATUS_CARD_DEFINITIONS = [
    ("POS Reconciliation - Total Records", "Total Records", "get_total_records_card", "POS Reconciliation Run"),
    ("POS Reconciliation - Cleared Records", "Cleared Records", "get_cleared_records_card", "POS Reconciliation Run"),
    ("POS Reconciliation - Pending Exceptions", "Pending Exceptions", "get_pending_exceptions_card", "POS Reconciliation Run"),
    ("POS Reconciliation - Manually Cleared", "Manually Cleared", "get_manual_cleared_card", "POS Reconciliation Run"),
    ("POS Reconciliation - Match Percent", "Match %", "get_match_percent_card", "POS Reconciliation Run"),
]

FINANCIAL_CARD_DEFINITIONS = [
    ("POS Reconciliation - Total Bank Amount", "Total Bank Amount", "get_total_amount_card", "Bank POS Transaction", "SAR"),
    ("POS Reconciliation - Mada Amount", "Mada Amount", "get_mada_amount_card", "Bank POS Transaction", "SAR"),
    ("POS Reconciliation - Visa Amount", "Visa Amount", "get_visa_amount_card", "Bank POS Transaction", "SAR"),
    ("POS Reconciliation - Mastercard Amount", "Mastercard Amount", "get_mastercard_amount_card", "Bank POS Transaction", "SAR"),
    ("POS Reconciliation - Commission", "Commission", "get_total_commission_card", "Bank POS Transaction", "SAR"),
    ("POS Reconciliation - Commission Percent", "Commission %", "get_commission_percent_card", "Bank POS Transaction", None),
    ("POS Reconciliation - Commission VAT", "VAT on Commission", "get_commission_vat_card", "Bank POS Transaction", "SAR"),
]

ALL_CARD_NAMES = [row[0] for row in STATUS_CARD_DEFINITIONS] + [row[0] for row in FINANCIAL_CARD_DEFINITIONS]

CARD_RAW_VALUES = {
    "MADA": ("SPAN", "MADA", "P1"),
    "VISA": ("VISA", "VC"),
    "MASTERCARD": ("MASTER_CARD", "MASTER CARD", "MASTERCARD", "MC"),
    "GCC CARD": ("GCCCARD", "GCC_CARD", "GCC CARD"),
    "AMERICAN EXPRESS": ("AMEX", "AMERICAN_EXPRESS", "AMERICAN EXPRESS"),
}


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
        "show_full_number": 1 if document_type == "POS Reconciliation Run" else 0,
        "currency": currency or "",
    }


def _check_read_permission(doctype):
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(_("Not permitted to read {0}.").format(doctype), frappe.PermissionError)


def _latest_completed_run():
    _check_read_permission("POS Reconciliation Run")
    rows = frappe.get_all(
        "POS Reconciliation Run",
        filters={"status": "Completed"},
        fields=[
            "name",
            "from_date",
            "to_date",
            "pos_profile",
            "card_type",
            "matching_count",
            "discrepancy_count",
            "bank_only_count",
            "alhamrani_only_count",
            "manually_cleared_count",
            "pending_count",
            "last_reconciled_on",
        ],
        order_by="last_reconciled_on desc, modified desc",
        limit_page_length=1,
    )
    return frappe._dict(rows[0]) if rows else None


def _result(value, fieldtype, route=None, route_options=None):
    result = {"value": value, "fieldtype": fieldtype}
    if route:
        result["route"] = route
    if route_options:
        result["route_options"] = route_options
    return result


def _results_route(run, **filters):
    if not run:
        return ["List", "POS Reconciliation Run"], None
    options = {"run": run.name}
    options.update({key: value for key, value in filters.items() if value not in (None, "")})
    return ["query-report", "POS Reconciliation Results"], options


def _run_total(run):
    if not run:
        return 0
    return sum(
        int(run.get(fieldname) or 0)
        for fieldname in ("matching_count", "discrepancy_count", "bank_only_count", "alhamrani_only_count")
    )


def _financial_route(run, card_label=None):
    if not run:
        return ["List", "POS Reconciliation Run"], None
    options = {
        "from_date": run.from_date,
        "to_date": run.to_date,
    }
    if run.pos_profile:
        options["pos_profile"] = run.pos_profile
    if card_label:
        options["card_type"] = card_label
    elif run.card_type:
        options["card_type"] = run.card_type
    return ["query-report", "POS Card Type Summary by Store"], options


def _raw_values_for(normalized_card_type):
    normalized = normalize_card_type(normalized_card_type)
    return CARD_RAW_VALUES.get(normalized, (normalized,)) if normalized else ()


def _financial_summary(run, requested_card_type=None):
    _check_read_permission("Bank POS Transaction")
    if not run:
        return frappe._dict(amount=0.0, commission=0.0, vat=0.0)

    run_card_type = normalize_card_type(run.card_type) if run.card_type else None
    requested = normalize_card_type(requested_card_type) if requested_card_type else None
    if run_card_type and requested and run_card_type != requested:
        return frappe._dict(amount=0.0, commission=0.0, vat=0.0)

    effective_card_type = requested or run_card_type
    conditions = [
        "transaction_date between %(from_date)s and %(to_date)s",
        "upper(coalesce(transaction_status, '')) = 'APPROVED'",
    ]
    params = {"from_date": run.from_date, "to_date": run.to_date}

    if run.pos_profile:
        conditions.append("pos_profile = %(pos_profile)s")
        params["pos_profile"] = run.pos_profile

    if effective_card_type:
        raw_values = tuple(value.upper() for value in _raw_values_for(effective_card_type))
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


@frappe.whitelist()
def get_total_records_card(filters=None):
    run = _latest_completed_run()
    route, options = _results_route(run)
    return _result(_run_total(run), "Int", route, options)


@frappe.whitelist()
def get_cleared_records_card(filters=None):
    run = _latest_completed_run()
    value = int(run.matching_count or 0) + int(run.manually_cleared_count or 0) if run else 0
    if run:
        return _result(value, "Int", ["Form", "POS Reconciliation Run", run.name])
    return _result(value, "Int", ["List", "POS Reconciliation Run"])


@frappe.whitelist()
def get_pending_exceptions_card(filters=None):
    run = _latest_completed_run()
    route, options = _results_route(run, resolution_status="Pending")
    return _result(int(run.pending_count or 0) if run else 0, "Int", route, options)


@frappe.whitelist()
def get_manual_cleared_card(filters=None):
    run = _latest_completed_run()
    route, options = _results_route(run, resolution_status="Manually Cleared")
    return _result(int(run.manually_cleared_count or 0) if run else 0, "Int", route, options)


@frappe.whitelist()
def get_match_percent_card(filters=None):
    run = _latest_completed_run()
    total = _run_total(run)
    value = (flt(run.matching_count) / total * 100) if run and total else 0.0
    route, options = _results_route(run, match_status="Matching")
    return _result(flt(value, 2), "Percent", route, options)


@frappe.whitelist()
def get_total_amount_card(filters=None):
    run = _latest_completed_run()
    summary = _financial_summary(run)
    route, options = _financial_route(run)
    return _result(summary.amount, "Currency", route, options)


def _card_amount(card_type, label):
    run = _latest_completed_run()
    summary = _financial_summary(run, card_type)
    route, options = _financial_route(run, label)
    return _result(summary.amount, "Currency", route, options)


@frappe.whitelist()
def get_mada_amount_card(filters=None):
    return _card_amount("MADA", "Mada")


@frappe.whitelist()
def get_visa_amount_card(filters=None):
    return _card_amount("VISA", "Visa")


@frappe.whitelist()
def get_mastercard_amount_card(filters=None):
    return _card_amount("MASTERCARD", "Mastercard")


@frappe.whitelist()
def get_total_commission_card(filters=None):
    run = _latest_completed_run()
    summary = _financial_summary(run)
    if run:
        route = ["query-report", "POS Commission by Store and Device"]
        options = {"from_date": run.from_date, "to_date": run.to_date}
        if run.pos_profile:
            options["pos_profile"] = run.pos_profile
        if run.card_type:
            options["card_type"] = run.card_type
    else:
        route, options = ["List", "POS Reconciliation Run"], None
    return _result(summary.commission, "Currency", route, options)


@frappe.whitelist()
def get_commission_percent_card(filters=None):
    run = _latest_completed_run()
    summary = _financial_summary(run)
    value = (summary.commission / summary.amount * 100) if summary.amount else 0.0
    if run:
        route = ["query-report", "POS Commission by Store and Device"]
        options = {"from_date": run.from_date, "to_date": run.to_date}
        if run.pos_profile:
            options["pos_profile"] = run.pos_profile
        if run.card_type:
            options["card_type"] = run.card_type
    else:
        route, options = ["List", "POS Reconciliation Run"], None
    return _result(flt(value, 4), "Percent", route, options)


@frappe.whitelist()
def get_commission_vat_card(filters=None):
    run = _latest_completed_run()
    summary = _financial_summary(run)
    if run:
        route = ["query-report", "POS Commission by Store and Device"]
        options = {"from_date": run.from_date, "to_date": run.to_date}
        if run.pos_profile:
            options["pos_profile"] = run.pos_profile
        if run.card_type:
            options["card_type"] = run.card_type
    else:
        route, options = ["List", "POS Reconciliation Run"], None
    return _result(summary.vat, "Currency", route, options)
