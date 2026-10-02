from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

CARD_TYPE_LABELS = {
    "SPAN": "Mada",
    "VISA": "Visa",
    "MASTER_CARD": "Mastercard",
    "GCCCARD": "GCC Card",
    "AMEX": "American Express",
}

CARD_FILTER_VALUES = {label.upper(): raw for raw, label in CARD_TYPE_LABELS.items()}
CARD_FILTER_VALUES.update({raw.upper(): raw for raw in CARD_TYPE_LABELS})


def display_card_type(raw_value):
    raw = str(raw_value or "").strip().upper()
    return CARD_TYPE_LABELS.get(raw, raw or _("Unknown"))


def raw_card_type(filter_value):
    value = str(filter_value or "").strip()
    if not value:
        return None
    return CARD_FILTER_VALUES.get(value.upper(), value.upper())


def commission_pct(commission, amount):
    amount = flt(amount)
    return (flt(commission) / amount * 100) if amount else 0.0


def validate_filters(filters):
    if not filters.from_date or not filters.to_date:
        frappe.throw(_("From Date and To Date are required."))
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_("From Date cannot be after To Date."))


def get_where_clause(filters):
    conditions = [
        "transaction_date between %(from_date)s and %(to_date)s",
        "upper(coalesce(transaction_status, '')) = 'APPROVED'",
    ]
    params = {
        "from_date": filters.from_date,
        "to_date": filters.to_date,
    }

    if filters.get("pos_profile"):
        conditions.append("pos_profile = %(pos_profile)s")
        params["pos_profile"] = filters.pos_profile

    card_type = raw_card_type(filters.get("card_type"))
    if card_type:
        conditions.append("card_type = %(card_type)s")
        params["card_type"] = card_type

    return " and ".join(conditions), params


def card_filter_options():
    return ["", "Mada", "Visa", "Mastercard", "GCC Card", "American Express"]
