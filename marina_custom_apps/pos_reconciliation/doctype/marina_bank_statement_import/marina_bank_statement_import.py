from __future__ import annotations

import frappe
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.marina_bank_statement_import_service import (
    get_import_status,
    start_import,
    validate_import,
)


class MarinaBankStatementImport(Document):
    pass


@frappe.whitelist()
def validate_statement(name):
    return validate_import(name)


@frappe.whitelist()
def start_statement_import(name, acknowledge_possible_duplicates=0):
    return start_import(name, acknowledge_possible_duplicates=acknowledge_possible_duplicates)


@frappe.whitelist()
def get_status(name):
    return get_import_status(name)
