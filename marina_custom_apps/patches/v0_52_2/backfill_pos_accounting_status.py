from __future__ import annotations

import frappe


def execute():
    from marina_custom_apps.pos_reconciliation.accounting_service import sync_all_accounting_statuses

    sync_all_accounting_statuses()
    frappe.clear_cache()
