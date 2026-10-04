from __future__ import annotations

import frappe

SETTINGS_DOCTYPE = "POS Reconciliation Settings"
MAPPING_DOCTYPE = "POS Card Type Mapping"
PARENT_FIELD = "card_type_mappings"

DEFAULT_MAPPINGS = [
    ("P1", "MADA", "MADA"),
    ("MADA", "SPAN", "MADA"),
    ("SPAN", "P1", "MADA"),
    ("VC", "VISA", "VISA"),
    ("VISA", "VC", "VISA"),
    ("MC", "MASTER_CARD", "MASTERCARD"),
    ("MASTER_CARD", "MASTER CARD", "MASTERCARD"),
    ("MASTER CARD", "MASTERCARD", "MASTERCARD"),
    ("MASTERCARD", "MC", "MASTERCARD"),
    ("GCCCARD", "GCC CARD", "GCC CARD"),
    ("GCC_CARD", "GCCCARD", "GCC CARD"),
    ("GCC CARD", "GCC_CARD", "GCC CARD"),
    ("AMEX", "AMERICAN E", "AMERICAN EXPRESS"),
    ("AMERICAN_EXPRESS", "AMERICAN EX", "AMERICAN EXPRESS"),
    ("AMERICAN EXPRESS", "AMERICAN_EXPRESS", "AMERICAN EXPRESS"),
    (None, "AMERICAN EXPRESS", "AMERICAN EXPRESS"),
    (None, "AMEX", "AMERICAN EXPRESS"),
]


def _clean(value):
    return (value or "").strip().upper()


def _mapping_key(bank_card_type, alhamrani_card_type, unified_card_type):
    return (
        _clean(bank_card_type),
        _clean(alhamrani_card_type),
        _clean(unified_card_type),
    )


def execute():
    """Seed mapping rows without saving the Single Settings document.

    The original v0.52.6 implementation saved the Settings document, which invokes
    unrelated POS Reconciliation Settings validation during bench migrate.
    This patch inserts only missing child rows directly and is safe to retry
    after a partially failed migration.
    """
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return

    if not frappe.db.exists("DocType", MAPPING_DOCTYPE):
        return

    existing = frappe.get_all(
        MAPPING_DOCTYPE,
        filters={
            "parent": SETTINGS_DOCTYPE,
            "parenttype": SETTINGS_DOCTYPE,
            "parentfield": PARENT_FIELD,
        },
        fields=[
            "bank_card_type",
            "alhamrani_card_type",
            "unified_card_type",
            "idx",
        ],
        order_by="idx asc",
        limit_page_length=0,
    )

    existing_keys = {
        _mapping_key(
            row.bank_card_type,
            row.alhamrani_card_type,
            row.unified_card_type,
        )
        for row in existing
    }

    next_idx = max((int(row.idx or 0) for row in existing), default=0) + 1

    for bank_card_type, alhamrani_card_type, unified_card_type in DEFAULT_MAPPINGS:
        key = _mapping_key(
            bank_card_type,
            alhamrani_card_type,
            unified_card_type,
        )
        if key in existing_keys:
            continue

        child = frappe.get_doc(
            {
                "doctype": MAPPING_DOCTYPE,
                "parent": SETTINGS_DOCTYPE,
                "parenttype": SETTINGS_DOCTYPE,
                "parentfield": PARENT_FIELD,
                "idx": next_idx,
                "bank_card_type": bank_card_type,
                "alhamrani_card_type": alhamrani_card_type,
                "unified_card_type": unified_card_type,
            }
        )
        child.db_insert()

        existing_keys.add(key)
        next_idx += 1