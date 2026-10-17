from __future__ import annotations

import json

import frappe


WORKSPACE = "POS Reconciliation"
REMOVE_DOCTYPES = {
    "POS Bank Statement Reconciliation",
    "POS Bank Settlement",
}
ADD_SHORTCUTS = [
    ("Marina Bank Statement Import", "Bank Statement Import", "Green"),
    ("Marina Bank Statement Transaction", "Bank Statement Transactions", "Blue"),
]


def _migrate_record_statuses():
    if not frappe.db.exists("DocType", "POS Reconciliation Record"):
        return

    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record`
        SET
            match_status = 'Matching Not Settled',
            resolution_status = CASE
                WHEN resolution_status = 'Manually Cleared' THEN 'Manually Cleared'
                ELSE 'One Side Matching'
            END
        WHERE match_status = 'Matching'
        """
    )

    # Previous experimental runs referenced standard ERPNext Bank Transaction
    # evidence and the separate POS Bank Statement Reconciliation doctype.
    # Reset only that statement-evidence projection; a unified POS run will
    # repopulate it from Marina Bank Statement Transaction.
    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record`
        SET
            bank_statement_status = 'Not Checked',
            bank_statement_reconciliation = NULL,
            bank_statement_settlement = NULL,
            bank_statement_references = NULL,
            bank_statement_checked_on = NULL
        """
    )


def _clean_workspace():
    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False

    shortcuts = workspace.get("shortcuts") or []
    for row in list(shortcuts):
        if row.type == "DocType" and row.link_to in REMOVE_DOCTYPES:
            shortcuts.remove(row)
            changed = True

    links = workspace.get("links") or []
    for row in list(links):
        if row.type == "Link" and row.link_type == "DocType" and row.link_to in REMOVE_DOCTYPES:
            links.remove(row)
            changed = True

    existing_shortcuts = {
        row.link_to
        for row in shortcuts
        if row.type == "DocType" and row.link_to
    }
    for doctype, label, color in ADD_SHORTCUTS:
        if doctype not in existing_shortcuts:
            workspace.append(
                "shortcuts",
                {
                    "type": "DocType",
                    "link_to": doctype,
                    "doc_view": "",
                    "label": label,
                    "color": color,
                },
            )
            changed = True

    existing_links = {
        row.link_to
        for row in links
        if row.type == "Link" and row.link_type == "DocType" and row.link_to
    }
    for doctype, label, _color in ADD_SHORTCUTS:
        if doctype not in existing_links:
            workspace.append(
                "links",
                {
                    "type": "Link",
                    "label": label,
                    "link_type": "DocType",
                    "link_to": doctype,
                    "is_query_report": 0,
                    "onboard": 1,
                    "hidden": 0,
                },
            )
            changed = True

    try:
        blocks = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        blocks = []
    if not isinstance(blocks, list):
        blocks = []

    remove_labels = {
        row.label
        for row in shortcuts
        if row.type == "DocType" and row.link_to in REMOVE_DOCTYPES
    } | {
        "Bank Statement Reconciliation",
        "POS Bank Settlements",
    }
    new_blocks = []
    for block in blocks:
        if block.get("type") == "shortcut":
            shortcut_name = block.get("data", {}).get("shortcut_name")
            if shortcut_name in remove_labels:
                changed = True
                continue
        new_blocks.append(block)

    existing_block_names = {
        block.get("data", {}).get("shortcut_name")
        for block in new_blocks
        if block.get("type") == "shortcut"
    }
    for idx, (_doctype, label, _color) in enumerate(ADD_SHORTCUTS):
        if label not in existing_block_names:
            new_blocks.append(
                {
                    "id": f"pos-bank-statement-v053-{idx}",
                    "type": "shortcut",
                    "data": {"shortcut_name": label, "col": 3},
                }
            )
            changed = True

    if changed:
        workspace.content = json.dumps(new_blocks, separators=(",", ":"))
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)
        frappe.clear_cache()


def execute():
    _migrate_record_statuses()
    _clean_workspace()
