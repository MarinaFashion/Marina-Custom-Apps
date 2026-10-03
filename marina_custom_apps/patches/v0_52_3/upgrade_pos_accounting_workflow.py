from __future__ import annotations

import frappe


SETTINGS_DOCTYPE = "POS Reconciliation Settings"


def execute():
    # Preserve the intended defaults for existing Single settings records.
    if frappe.db.get_single_value(SETTINGS_DOCTYPE, "consolidate_bank_entries") is None:
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "consolidate_bank_entries", 1)

    if not frappe.db.get_single_value(SETTINGS_DOCTYPE, "journal_entry_creation_mode"):
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "journal_entry_creation_mode", "Draft")

    from marina_custom_apps.pos_reconciliation.accounting_service import sync_all_accounting_statuses

    sync_all_accounting_statuses()
