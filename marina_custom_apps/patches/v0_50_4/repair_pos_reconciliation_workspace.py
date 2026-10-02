from __future__ import annotations

import json

import frappe

from marina_custom_apps.patches.v0_50_1.ensure_pos_reconciliation_workspace import (
    FINANCIAL_CARDS,
    STATUS_CARDS,
    execute as ensure_workspace,
)
from marina_custom_apps.pos_reconciliation.dashboard_cards import ALL_CARD_NAMES

WORKSPACE = "POS Reconciliation"


def execute():
    # First re-run the original idempotent workspace builder so missing reports,
    # shortcuts, card documents, and content blocks are restored.
    ensure_workspace()

    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False

    changed |= _repair_number_card_rows(workspace)
    changed |= _repair_number_card_blocks(workspace)

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)

    frappe.clear_cache()


def _repair_number_card_rows(workspace):
    """Make Workspace Number Card.label match the block's number_card_name.

    Frappe v15 joins a number-card content block to the Workspace Number Card
    child row by the child row's `label`, not by `number_card_name`. v0.50.1
    used the short display label (for example `Total Records`), while the block
    contains the full Number Card name (for example
    `POS Reconciliation - Total Records`). That leaves the block without a
    matching widget row and nothing is rendered.
    """
    changed = False
    seen = set()

    for row in list(workspace.get("number_cards") or []):
        name = row.number_card_name
        if name not in ALL_CARD_NAMES:
            continue

        if name in seen:
            workspace.remove(row)
            changed = True
            continue

        seen.add(name)
        if row.label != name:
            row.label = name
            changed = True

    for name in ALL_CARD_NAMES:
        if name in seen:
            continue
        workspace.append(
            "number_cards",
            {
                "number_card_name": name,
                "label": name,
            },
        )
        seen.add(name)
        changed = True

    return changed


def _repair_number_card_blocks(workspace):
    try:
        content = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        content = []

    if not isinstance(content, list):
        content = []

    changed = False
    seen = set()
    repaired = []

    # Preserve all user/manual workspace content. Only de-duplicate Marina's
    # own reconciliation KPI blocks when the exact same card occurs twice.
    for block in content:
        if block.get("type") == "number_card":
            name = block.get("data", {}).get("number_card_name")
            if name in ALL_CARD_NAMES:
                if name in seen:
                    changed = True
                    continue
                seen.add(name)
        repaired.append(block)

    # The v0.50.1 builder should normally have created all blocks. This is a
    # safety net for sites where a manual workspace edit removed one or more.
    missing_status = [name for name in STATUS_CARDS if name not in seen]
    missing_financial = [name for name in FINANCIAL_CARDS if name not in seen]

    if missing_status or missing_financial:
        insert_at = 1 if repaired and repaired[0].get("type") == "header" else 0
        additions = []

        if missing_status:
            if not _has_header(repaired, "Reconciliation Status"):
                additions.append(_header_block("pr-kpi-status-head-v0504", "Reconciliation Status – Latest Completed Run"))
            for idx, name in enumerate(missing_status, start=1):
                additions.append(_number_card_block(f"pr-kpi-s-v0504-{idx}", name, 3))

        if missing_financial:
            if not _has_header(repaired, "Financial Summary"):
                additions.append(_header_block("pr-kpi-fin-head-v0504", "Financial Summary – Same Run Period"))
            for idx, name in enumerate(missing_financial, start=1):
                col = 3 if name in FINANCIAL_CARDS[:4] else 4
                additions.append(_number_card_block(f"pr-kpi-f-v0504-{idx}", name, col))

        repaired[insert_at:insert_at] = additions
        changed = True

    if changed:
        workspace.content = json.dumps(repaired, separators=(",", ":"))

    return changed


def _has_header(content, text):
    return any(
        block.get("type") == "header" and text in block.get("data", {}).get("text", "")
        for block in content
    )


def _header_block(block_id, title):
    return {
        "id": block_id,
        "type": "header",
        "data": {"text": f'<span class="h4"><b>{title}</b></span>', "col": 12},
    }


def _number_card_block(block_id, name, col):
    return {
        "id": block_id,
        "type": "number_card",
        "data": {"number_card_name": name, "col": col},
    }
