from __future__ import annotations

import frappe

SETTINGS = "POS Reconciliation Settings"
WORKSPACE = "POS Reconciliation"

DEFAULT_CODE_MAPPINGS = [
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

DOC_SHORTCUTS = [
    ("POS Bank Statement Reconciliation", "Bank Statement Reconciliation", "Blue"),
    ("POS Bank Settlement", "POS Bank Settlements", "Green"),
]


def execute():
    _seed_statement_settings()
    _update_workspace()
    frappe.clear_cache()


def _seed_statement_settings():
    settings = frappe.get_single(SETTINGS)
    changed = False

    if not settings.bank_statement_terminal_reference_length:
        settings.bank_statement_terminal_reference_length = 8
        changed = True

    if not settings.bank_statement_reconciliation_lookback_days:
        settings.bank_statement_reconciliation_lookback_days = 7
        changed = True

    existing = {
        (
            (row.code or "").strip().upper(),
            (row.card_type or "").strip().upper(),
            (row.component or "").strip(),
        )
        for row in settings.get("bank_statement_code_mappings") or []
    }

    for code, card_type, component in DEFAULT_CODE_MAPPINGS:
        key = (code, card_type, component)
        if key in existing:
            continue
        settings.append(
            "bank_statement_code_mappings",
            {
                "code": code,
                "card_type": card_type,
                "component": component,
                "active": 1,
            },
        )
        existing.add(key)
        changed = True

    if changed:
        settings.save(ignore_permissions=True)


def _update_workspace():
    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False

    shortcut_keys = {
        (row.type, row.link_to)
        for row in workspace.get("shortcuts") or []
        if row.link_to
    }
    for link_to, label, color in DOC_SHORTCUTS:
        key = ("DocType", link_to)
        if key in shortcut_keys:
            continue
        workspace.append(
            "shortcuts",
            {
                "type": "DocType",
                "link_to": link_to,
                "doc_view": "List",
                "label": label,
                "color": color,
            },
        )
        shortcut_keys.add(key)
        changed = True

    existing_links = {
        row.link_to
        for row in workspace.get("links") or []
        if row.type == "Link" and row.link_type == "DocType" and row.link_to
    }
    for link_to, label, _color in DOC_SHORTCUTS:
        if link_to in existing_links:
            continue
        workspace.append(
            "links",
            {
                "type": "Link",
                "label": label,
                "link_type": "DocType",
                "link_to": link_to,
                "is_query_report": 0,
                "onboard": 1,
                "hidden": 0,
            },
        )
        existing_links.add(link_to)
        changed = True

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)
