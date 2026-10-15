from __future__ import annotations

import frappe


def execute():
    if not frappe.db.exists("DocType", "Bank Statement Reconciliation Match"):
        return

    options = "Auto Reference\nManual TR"
    frappe.db.set_value(
        "DocField",
        {
            "parent": "Bank Statement Reconciliation Match",
            "fieldname": "match_type",
        },
        "options",
        options,
        update_modified=False,
    )
    frappe.clear_cache(doctype="Bank Statement Reconciliation Match")
