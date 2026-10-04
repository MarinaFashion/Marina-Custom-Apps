from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.bank_import_service import (
    clear_import_summary,
    get_import_status,
    set_tool_enabled,
    start_import,
    validate_import_file,
)


class POSBankImport(Document):
    pass


@frappe.whitelist()
def validate_file(file_url=None):
    return validate_import_file(file_url)


@frappe.whitelist()
def start_bank_import(file_url=None):
    return start_import(file_url)


@frappe.whitelist()
def get_status():
    return get_import_status()


@frappe.whitelist()
def clear_summary():
    return clear_import_summary()


@frappe.whitelist()
def toggle_tool(enabled=1):
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager can enable or disable the Bank Import Tool."), frappe.PermissionError)
    return set_tool_enabled(enabled)
