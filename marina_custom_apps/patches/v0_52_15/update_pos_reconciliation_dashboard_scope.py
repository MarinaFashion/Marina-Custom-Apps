from __future__ import annotations

import json

import frappe

from marina_custom_apps.pos_reconciliation.dashboard_cards import (
    LEGACY_CARD_TYPE_CARDS,
    number_card_documents,
)

WORKSPACE = "POS Reconciliation"
CHART_NAME = "POS Reconciliation Amount by Card Type"


def execute():
    _ensure_number_cards()
    _ensure_dashboard_chart()

    if not frappe.db.exists("Workspace", WORKSPACE):
        frappe.clear_cache()
        return

    workspace = frappe.get_doc("Workspace", WORKSPACE)
    changed = False
    changed |= _update_number_card_rows(workspace)
    changed |= _ensure_chart_row(workspace)
    changed |= _update_workspace_content(workspace)

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)

    frappe.clear_cache()


def _ensure_number_cards():
    for definition in number_card_documents():
        name = definition["name"]
        values = {key: value for key, value in definition.items() if key not in {"doctype", "name"}}
        if frappe.db.exists("Number Card", name):
            frappe.db.set_value("Number Card", name, values, update_modified=True)
        else:
            frappe.get_doc(definition).insert(ignore_permissions=True)


def _ensure_dashboard_chart():
    values = {
        "chart_name": CHART_NAME,
        "chart_type": "Report",
        "report_name": "POS Reconciliation Card Type Summary",
        "use_report_chart": 1,
        "type": "Bar",
        "is_public": 1,
        "is_standard": 0,
        "module": "POS Reconciliation",
        "filters_json": "{}",
        "dynamic_filters_json": "{}",
        "currency": "SAR",
        "show_values_over_chart": 1,
        "custom_options": '{"type":"bar","axisOptions":{"shortenYAxisNumbers":1},"barOptions":{"stacked":0}}',
    }
    if frappe.db.exists("Dashboard Chart", CHART_NAME):
        frappe.db.set_value("Dashboard Chart", CHART_NAME, values, update_modified=True)
    else:
        frappe.get_doc({"doctype": "Dashboard Chart", **values}).insert(ignore_permissions=True)


def _update_number_card_rows(workspace):
    changed = False
    current_names = {definition["name"] for definition in number_card_documents()}

    for row in list(workspace.get("number_cards") or []):
        if row.number_card_name in LEGACY_CARD_TYPE_CARDS:
            workspace.remove(row)
            changed = True

    existing = {row.number_card_name for row in workspace.get("number_cards") or [] if row.number_card_name}
    for name in current_names:
        if name not in existing:
            workspace.append("number_cards", {"number_card_name": name, "label": name})
            changed = True

    for row in workspace.get("number_cards") or []:
        if row.number_card_name in current_names and row.label != row.number_card_name:
            row.label = row.number_card_name
            changed = True

    return changed


def _ensure_chart_row(workspace):
    changed = False
    found = False
    for row in list(workspace.get("charts") or []):
        if row.chart_name != CHART_NAME:
            continue
        if found:
            workspace.remove(row)
            changed = True
            continue
        found = True
        if row.label != CHART_NAME:
            row.label = CHART_NAME
            changed = True

    if not found:
        workspace.append("charts", {"chart_name": CHART_NAME, "label": CHART_NAME})
        changed = True
    return changed


def _update_workspace_content(workspace):
    try:
        content = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        content = []
    if not isinstance(content, list):
        content = []

    changed = False
    rebuilt = []
    chart_found = False

    for block in content:
        data = block.get("data", {})
        if block.get("type") == "number_card" and data.get("number_card_name") in LEGACY_CARD_TYPE_CARDS:
            changed = True
            continue

        if block.get("type") == "header":
            text = data.get("text", "")
            if "Reconciliation Status" in text and "Latest Completed Run" in text:
                block = {
                    **block,
                    "data": {**data, "text": '<span class="h4"><b>Reconciliation Status – All Reconciliation Transactions</b></span>'},
                }
                changed = True
            elif "Financial Summary" in text and "Same Run Period" in text:
                block = {
                    **block,
                    "data": {**data, "text": '<span class="h4"><b>Financial Summary – All Approved Bank Transactions</b></span>'},
                }
                changed = True

        if block.get("type") == "chart" and data.get("chart_name") == CHART_NAME:
            if chart_found:
                changed = True
                continue
            chart_found = True

        rebuilt.append(block)

    if not chart_found:
        financial_card_names = {
            definition["name"]
            for definition in number_card_documents()
            if definition["document_type"] == "Bank POS Transaction"
        }
        positions = [
            index
            for index, block in enumerate(rebuilt)
            if block.get("type") == "number_card"
            and block.get("data", {}).get("number_card_name") in financial_card_names
        ]
        insert_at = max(positions) + 1 if positions else len(rebuilt)
        rebuilt.insert(
            insert_at,
            {
                "id": "pr-card-type-chart-v05215",
                "type": "chart",
                "data": {"chart_name": CHART_NAME, "col": 12},
            },
        )
        changed = True

    if changed:
        workspace.content = json.dumps(rebuilt, separators=(",", ":"))
    return changed
