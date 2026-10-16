from __future__ import annotations

import json

import frappe

WORKSPACE = "POS Reconciliation"
DOCTYPE = "Bank Reconciliation Exclusion"
SHORTCUT = "Excluded Bank Transactions"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return
    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False

    if not any(row.link_to == DOCTYPE for row in workspace.get("shortcuts") or []):
        workspace.append("shortcuts", {
            "type": "DocType",
            "link_to": DOCTYPE,
            "doc_view": "List",
            "label": SHORTCUT,
            "color": "Grey",
        })
        changed = True

    if not any(row.link_type == "DocType" and row.link_to == DOCTYPE for row in workspace.get("links") or []):
        workspace.append("links", {
            "type": "Link",
            "label": DOCTYPE,
            "link_type": "DocType",
            "link_to": DOCTYPE,
            "hidden": 0,
            "onboard": 0,
            "is_query_report": 0,
        })
        changed = True

    try:
        blocks = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        blocks = []
    if not isinstance(blocks, list):
        blocks = []
    if not any(
        block.get("type") == "shortcut"
        and block.get("data", {}).get("shortcut_name") == SHORTCUT
        for block in blocks
    ):
        pos = next(
            (i + 1 for i, block in enumerate(blocks)
             if block.get("type") == "shortcut"
             and block.get("data", {}).get("shortcut_name") == "Bank Reconciliation Matches"),
            len(blocks),
        )
        blocks.insert(pos, {
            "id": "pr-s-exclusions",
            "type": "shortcut",
            "data": {"shortcut_name": SHORTCUT, "col": 3},
        })
        workspace.content = json.dumps(blocks, separators=(",", ":"))
        changed = True

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)
        frappe.clear_cache()
