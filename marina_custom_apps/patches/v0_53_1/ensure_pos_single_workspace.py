"""Keep the POS workspace shortcuts aligned with the Single control."""

from __future__ import annotations

import json
import frappe


def execute():
    if not frappe.db.exists("Workspace", "POS Reconciliation"):
        return
    doc = frappe.get_doc("Workspace", "POS Reconciliation")
    changed = False
    for row in doc.get("shortcuts") or []:
        if row.link_to == "POS Reconciliation Run":
            # Frappe Workspace Shortcut.doc_view does not support "Form".
            # Blank is valid and Frappe routes Singles directly to their form.
            if row.label != "Reconciliation Control" or row.doc_view:
                row.label = "Reconciliation Control"
                row.doc_view = ""
                changed = True
    for label, link in (
        ("Execution History", "POS Reconciliation Execution"),
        ("Period Locks", "POS Reconciliation Period Lock"),
    ):
        if not any(r.link_to == link for r in (doc.get("shortcuts") or [])):
            doc.append("shortcuts", {
                "label": label, "type": "DocType", "link_to": link,
                "doc_view": "List", "color": "Grey",
            })
            changed = True
        if not any(r.link_to == link for r in (doc.get("links") or [])):
            doc.append("links", {"type": "Link", "link_type": "DocType", "link_to": link, "label": link})
            changed = True

    try:
        content = json.loads(doc.content or "[]")
    except ValueError:
        content = []
    if isinstance(content, list):
        for item in content:
            if item.get("type") == "shortcut" and item.get("data", {}).get("shortcut_name") == "Reconciliation Runs":
                item["data"]["shortcut_name"] = "Reconciliation Control"
                changed = True
        known = {x.get("data", {}).get("shortcut_name") for x in content if x.get("type") == "shortcut"}
        for label, entry_id in (("Execution History", "pr-s-execution-history"), ("Period Locks", "pr-s-period-locks")):
            if label not in known:
                content.append({"id": entry_id, "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
                changed = True
        if changed:
            doc.content = json.dumps(content)

    if changed:
        doc.flags.ignore_permissions = True
        doc.save()
        frappe.clear_cache()
