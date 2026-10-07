from __future__ import annotations

from frappe import _

from marina_custom_apps.pos_reconciliation.dashboard_cards import (
    display_card_type,
    get_reconciliation_card_type_summary,
)


def execute(filters=None):
    rows = get_reconciliation_card_type_summary()
    data = [
        {
            "card_type": display_card_type(row.card_type),
            "transaction_count": row.transaction_count,
            "amount": row.amount,
        }
        for row in rows
    ]

    # One category per card type, matching the requested bar-chart layout.
    chart = {
        "data": {
            "labels": [row["card_type"] for row in data],
            "datasets": [
                {
                    "name": _("Amount"),
                    "values": [row["amount"] for row in data],
                }
            ],
        },
        "type": "bar",
        "height": 280,
        "axisOptions": {"shortenYAxisNumbers": 1},
        "barOptions": {"stacked": 0},
    }

    return get_columns(), data, None, chart


def get_columns():
    return [
        {
            "label": _("Card Type"),
            "fieldname": "card_type",
            "fieldtype": "Data",
            "width": 220,
        },
        {
            "label": _("Transactions"),
            "fieldname": "transaction_count",
            "fieldtype": "Int",
            "width": 120,
        },
        {
            "label": _("Amount"),
            "fieldname": "amount",
            "fieldtype": "Currency",
            "options": "SAR",
            "width": 160,
        },
    ]
