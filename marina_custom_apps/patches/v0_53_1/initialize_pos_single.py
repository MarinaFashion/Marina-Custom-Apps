from __future__ import annotations

import frappe


def execute():
    if not frappe.db.exists("DocType", "POS Reconciliation Run"):
        return
    frappe.db.set_single_value("POS Reconciliation Run", "status", "Draft")
    frappe.db.set_single_value("POS Reconciliation Run", "execution_status", "Idle")
    frappe.clear_cache(doctype="POS Reconciliation Run")
