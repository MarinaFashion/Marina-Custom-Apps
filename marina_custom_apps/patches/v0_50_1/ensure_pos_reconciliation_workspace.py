from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from marina_custom_apps.pos_reconciliation.dashboard_cards import (
    ALL_CARD_NAMES,
    number_card_documents,
)

WORKSPACE = "POS Reconciliation"

REPORT_LINKS = [
    ("POS Reconciliation Results", "Reconciliation Results", "Orange"),
    ("POS Commission by Store and Device", "Commission by Store & Device", "Blue"),
    ("POS Card Type Summary by Store", "Card Type Summary by Store", "Green"),
]

DOC_SHORTCUTS = [
    ("Bank POS Transaction", "Bank POS Transactions", "Blue"),
    ("Terminal Reference", "Terminal References", "Grey"),
    ("POS Reconciliation Run", "Reconciliation Runs", "Orange"),
    ("POS Reconciliation Record", "Reconciliation Records", "Red"),
]

STATUS_CARDS = [
    "POS Reconciliation - Total Records",
    "POS Reconciliation - Cleared Records",
    "POS Reconciliation - Pending Exceptions",
    "POS Reconciliation - Manually Cleared",
    "POS Reconciliation - Match Percent",
]

FINANCIAL_CARDS = [
    "POS Reconciliation - Total Bank Amount",
    "POS Reconciliation - Mada Amount",
    "POS Reconciliation - Visa Amount",
    "POS Reconciliation - Mastercard Amount",
    "POS Reconciliation - Commission",
    "POS Reconciliation - Commission Percent",
    "POS Reconciliation - Commission VAT",
]


def execute():
    _ensure_number_cards()
    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False
    changed |= _ensure_workspace_number_cards(workspace)
    changed |= _ensure_shortcuts(workspace)
    changed |= _ensure_navigation_links(workspace)
    changed |= _ensure_content(workspace)

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)

    frappe.clear_cache()


def _ensure_number_cards():
    definitions = number_card_documents()
    now = now_datetime()
    user = frappe.session.user or "Administrator"
    insert_fields = [
        "name",
        "owner",
        "creation",
        "modified",
        "modified_by",
        "docstatus",
        "idx",
        "label",
        "type",
        "method",
        "document_type",
        "is_public",
        "is_standard",
        "module",
        "filters_json",
        "dynamic_filters_json",
        "show_percentage_stats",
        "show_full_number",
        "currency",
    ]
    insert_values = []

    for definition in definitions:
        name = definition["name"]
        values = {key: value for key, value in definition.items() if key not in {"doctype", "name"}}
        if frappe.db.exists("Number Card", name):
            frappe.db.set_value("Number Card", name, values, update_modified=True)
            continue

        row = {
            "name": name,
            "owner": user,
            "creation": now,
            "modified": now,
            "modified_by": user,
            "docstatus": 0,
            "idx": 0,
            **values,
        }
        insert_values.append(tuple(row.get(fieldname) for fieldname in insert_fields))

    if insert_values:
        frappe.db.bulk_insert(
            "Number Card",
            fields=insert_fields,
            values=insert_values,
            ignore_duplicates=True,
        )


def _ensure_workspace_number_cards(workspace):
    existing = {row.number_card_name for row in workspace.get("number_cards") or []}
    changed = False
    for name in ALL_CARD_NAMES:
        if name in existing:
            continue
        label = frappe.db.get_value("Number Card", name, "label") or name
        workspace.append("number_cards", {"number_card_name": name, "label": label})
        changed = True
    return changed


def _ensure_shortcuts(workspace):
    changed = False
    existing = {(row.type, row.link_to) for row in workspace.get("shortcuts") or []}

    for link_to, label, color in DOC_SHORTCUTS:
        key = ("DocType", link_to)
        if key not in existing:
            workspace.append(
                "shortcuts",
                {"type": "DocType", "link_to": link_to, "doc_view": "List", "label": label, "color": color},
            )
            existing.add(key)
            changed = True

    for link_to, label, color in REPORT_LINKS:
        key = ("Report", link_to)
        if key not in existing:
            workspace.append(
                "shortcuts",
                {"type": "Report", "link_to": link_to, "label": label, "color": color},
            )
            existing.add(key)
            changed = True

    return changed


def _ensure_navigation_links(workspace):
    changed = False
    links = workspace.get("links") or []

    if not any(row.type == "Card Break" and row.label == "POS Reconciliation" for row in links):
        workspace.append("links", {"type": "Card Break", "label": "POS Reconciliation", "hidden": 0, "link_count": 0})
        changed = True

    existing_doctypes = {
        row.link_to
        for row in workspace.get("links") or []
        if row.type == "Link" and row.link_type == "DocType" and row.link_to
    }
    for link_to, _label, _color in DOC_SHORTCUTS:
        if link_to in existing_doctypes:
            continue
        workspace.append(
            "links",
            {
                "type": "Link",
                "label": link_to,
                "link_type": "DocType",
                "link_to": link_to,
                "is_query_report": 0,
                "onboard": 1,
                "hidden": 0,
            },
        )
        existing_doctypes.add(link_to)
        changed = True

    if not any(row.type == "Card Break" and row.label == "Reports" for row in workspace.get("links") or []):
        workspace.append("links", {"type": "Card Break", "label": "Reports", "hidden": 0, "link_count": 0})
        changed = True

    existing_reports = {
        row.link_to
        for row in workspace.get("links") or []
        if row.type == "Link" and row.link_type == "Report" and row.link_to
    }
    for link_to, _label, _color in REPORT_LINKS:
        if link_to in existing_reports:
            continue
        workspace.append(
            "links",
            {
                "type": "Link",
                "label": link_to,
                "link_type": "Report",
                "link_to": link_to,
                "is_query_report": 1,
                "onboard": 0,
                "hidden": 0,
            },
        )
        existing_reports.add(link_to)
        changed = True

    return changed


def _header_block(block_id, title):
    return {
        "id": block_id,
        "type": "header",
        "data": {"text": f'<span class="h4"><b>{title}</b></span>', "col": 12},
    }


def _number_card_block(block_id, name, col=3):
    return {
        "id": block_id,
        "type": "number_card",
        "data": {"number_card_name": name, "col": col},
    }


def _report_shortcut_block(block_id, shortcut_name):
    return {
        "id": block_id,
        "type": "shortcut",
        "data": {"shortcut_name": shortcut_name, "col": 4},
    }


def _ensure_content(workspace):
    try:
        content = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        content = []

    if not isinstance(content, list):
        content = []

    changed = False
    card_names = {
        block.get("data", {}).get("number_card_name")
        for block in content
        if block.get("type") == "number_card"
    }
    shortcut_names = {
        block.get("data", {}).get("shortcut_name")
        for block in content
        if block.get("type") == "shortcut"
    }

    insert_at = 1 if content and content[0].get("type") == "header" else 0
    navigation_blocks = []
    for idx, (_link_to, shortcut_name, _color) in enumerate(DOC_SHORTCUTS, start=1):
        if shortcut_name not in shortcut_names:
            navigation_blocks.append(
                {"id": f"pr-sfix-{idx}", "type": "shortcut", "data": {"shortcut_name": shortcut_name, "col": 3}}
            )
            shortcut_names.add(shortcut_name)
    if navigation_blocks:
        content[insert_at:insert_at] = navigation_blocks
        insert_at += len(navigation_blocks)
        changed = True
    overview_blocks = []

    if not any(
        block.get("type") == "header" and "Reconciliation Status" in block.get("data", {}).get("text", "")
        for block in content
    ):
        overview_blocks.append(_header_block("pr-kpi-status-head", "Reconciliation Status – Latest Completed Run"))

    for idx, name in enumerate(STATUS_CARDS, start=1):
        if name not in card_names:
            overview_blocks.append(_number_card_block(f"pr-kpi-s{idx}", name, 3))
            card_names.add(name)

    if not any(
        block.get("type") == "header" and "Financial Summary" in block.get("data", {}).get("text", "")
        for block in content
    ):
        overview_blocks.append(_header_block("pr-kpi-fin-head", "Financial Summary – Same Run Period"))

    for idx, name in enumerate(FINANCIAL_CARDS, start=1):
        if name not in card_names:
            overview_blocks.append(_number_card_block(f"pr-kpi-f{idx}", name, 3 if idx <= 4 else 4))
            card_names.add(name)

    if overview_blocks:
        content[insert_at:insert_at] = overview_blocks
        changed = True

    report_shortcut_names = shortcut_names
    report_header_exists = any(
        block.get("type") == "header" and "Reports" in block.get("data", {}).get("text", "")
        for block in content
    )
    if not report_header_exists:
        content.append(_header_block("pr-rhead-fix", "Reports"))
        changed = True

    for idx, (_link_to, shortcut_name, _color) in enumerate(REPORT_LINKS, start=1):
        if shortcut_name not in report_shortcut_names:
            content.append(_report_shortcut_block(f"pr-rfix-{idx}", shortcut_name))
            report_shortcut_names.add(shortcut_name)
            changed = True

    if changed:
        workspace.content = json.dumps(content, separators=(",", ":"))
    return changed
