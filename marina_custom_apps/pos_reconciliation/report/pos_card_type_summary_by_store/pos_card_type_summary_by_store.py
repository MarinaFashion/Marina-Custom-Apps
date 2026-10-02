from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from marina_custom_apps.pos_reconciliation.reporting import (
    commission_pct,
    display_card_type,
    get_where_clause,
    validate_filters,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    validate_filters(filters)
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("POS Profile / Card Type"), "fieldname": "group_label", "fieldtype": "Data", "width": 240},
        {"label": _("Transactions"), "fieldname": "transaction_count", "fieldtype": "Int", "width": 100},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 140},
        {"label": _("Commission"), "fieldname": "commission", "fieldtype": "Currency", "width": 125},
        {"label": _("Commission %"), "fieldname": "commission_pct", "fieldtype": "Percent", "precision": 4, "width": 115},
        {"label": _("VAT"), "fieldname": "vat", "fieldtype": "Currency", "width": 110},
    ]


def get_data(filters):
    where_clause, params = get_where_clause(filters)
    rows = frappe.db.sql(
        f"""
        select
            coalesce(nullif(pos_profile, ''), '') as pos_profile,
            card_type,
            count(*) as transaction_count,
            sum(coalesce(transaction_amount, 0)) as amount,
            sum(coalesce(fee_amount, 0)) as commission,
            sum(coalesce(vat_amount, 0)) as vat
        from `tabBank POS Transaction`
        where {where_clause}
        group by pos_profile, card_type
        order by pos_profile asc, card_type asc
        """,
        params,
        as_dict=True,
    )

    grouped = defaultdict(list)
    for row in rows:
        grouped[row.pos_profile or ""].append(row)

    result = []
    grand = {"transaction_count": 0, "amount": 0.0, "commission": 0.0, "vat": 0.0}

    store_keys = sorted(grouped, key=lambda value: (not bool(value), value or ""))
    for pos_profile in store_keys:
        details = grouped[pos_profile]
        store = {
            "transaction_count": sum(int(row.transaction_count or 0) for row in details),
            "amount": sum(flt(row.amount) for row in details),
            "commission": sum(flt(row.commission) for row in details),
            "vat": sum(flt(row.vat) for row in details),
        }
        store["commission_pct"] = commission_pct(store["commission"], store["amount"])

        result.append(
            {
                "group_label": pos_profile or _("Unassigned POS Profile"),
                **store,
                "is_group": 1,
            }
        )

        for row in details:
            result.append(
                {
                    "group_label": f"↳ {display_card_type(row.card_type)}",
                    "transaction_count": int(row.transaction_count or 0),
                    "amount": flt(row.amount),
                    "commission": flt(row.commission),
                    "commission_pct": commission_pct(row.commission, row.amount),
                    "vat": flt(row.vat),
                    "is_group": 0,
                }
            )

        grand["transaction_count"] += store["transaction_count"]
        grand["amount"] += store["amount"]
        grand["commission"] += store["commission"]
        grand["vat"] += store["vat"]

    if rows:
        grand["commission_pct"] = commission_pct(grand["commission"], grand["amount"])
        result.append({"group_label": _("Grand Total"), **grand, "is_group": 1, "is_grand_total": 1})

    return result
