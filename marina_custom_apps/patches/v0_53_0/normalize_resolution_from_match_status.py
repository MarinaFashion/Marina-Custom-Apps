from __future__ import annotations

import frappe


def execute():
    rows = frappe.get_all(
        "POS Reconciliation Record",
        fields=["name", "match_status"],
        limit_page_length=0,
    )
    for row in rows:
        resolution = (
            "Auto Cleared"
            if row.match_status in {"Fully Matching", "Bank Only - Settled"}
            else "Pending"
        )
        frappe.db.set_value(
            "POS Reconciliation Record",
            row.name,
            "resolution_status",
            resolution,
            update_modified=False,
        )
