from __future__ import annotations

import frappe

SETTINGS_DOCTYPE = "POS Reconciliation Settings"
MAPPING_DOCTYPE = "POS Bank Statement Code Mapping"
PARENT_FIELD = "bank_statement_code_mappings"

DEFAULT_MAPPINGS = [
    ("SM", "MADA", "Gross"),
    ("FS", "MADA", "Commission"),
    ("VS", "MADA", "VAT"),
    ("VC", "VISA", "Gross"),
    ("FV", "VISA", "Commission"),
    ("VV", "VISA", "VAT"),
    ("MC", "MASTERCARD", "Gross"),
    ("FM", "MASTERCARD", "Commission"),
    ("VM", "MASTERCARD", "VAT"),
    ("GN", "GCCCARD", "Gross"),
    ("GF", "GCCCARD", "Commission"),
    ("GV", "GCCCARD", "VAT"),
    ("AX", "AMEX", "Gross"),
    ("AF", "AMEX", "Commission"),
    ("AV", "AMEX", "VAT"),
]


def _key(code, card_type, component):
    return (
        (code or "").strip().upper(),
        (card_type or "").strip().upper(),
        (component or "").strip(),
    )


def execute():
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return
    if not frappe.db.exists("DocType", MAPPING_DOCTYPE):
        return

    # Repair scalar Single values without invoking unrelated Settings validation.
    if not frappe.db.get_single_value(SETTINGS_DOCTYPE, "bank_statement_terminal_reference_length"):
        frappe.db.set_single_value(
            SETTINGS_DOCTYPE, "bank_statement_terminal_reference_length", 8
        )
    if not frappe.db.get_single_value(SETTINGS_DOCTYPE, "bank_statement_reconciliation_lookback_days"):
        frappe.db.set_single_value(
            SETTINGS_DOCTYPE, "bank_statement_reconciliation_lookback_days", 7
        )

    existing = frappe.get_all(
        MAPPING_DOCTYPE,
        filters={
            "parent": SETTINGS_DOCTYPE,
            "parenttype": SETTINGS_DOCTYPE,
            "parentfield": PARENT_FIELD,
        },
        fields=["code", "card_type", "component", "idx"],
        order_by="idx asc",
        limit_page_length=0,
    )
    existing_keys = {
        _key(row.code, row.card_type, row.component)
        for row in existing
    }
    next_idx = max((int(row.idx or 0) for row in existing), default=0) + 1

    for code, card_type, component in DEFAULT_MAPPINGS:
        mapping_key = _key(code, card_type, component)
        if mapping_key in existing_keys:
            continue

        child = frappe.get_doc(
            {
                "doctype": MAPPING_DOCTYPE,
                "parent": SETTINGS_DOCTYPE,
                "parenttype": SETTINGS_DOCTYPE,
                "parentfield": PARENT_FIELD,
                "idx": next_idx,
                "code": code,
                "card_type": card_type,
                "component": component,
                "active": 1,
            }
        )
        child.db_insert()
        existing_keys.add(mapping_key)
        next_idx += 1

    frappe.clear_cache(doctype=SETTINGS_DOCTYPE)
