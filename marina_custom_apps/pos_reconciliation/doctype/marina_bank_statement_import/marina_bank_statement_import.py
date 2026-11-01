from __future__ import annotations

import frappe
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.marina_bank_statement_import_service import (
    get_import_status,
    get_duplicate_review,
    start_import,
    validate_import,
)


class MarinaBankStatementImport(Document):
    pass


@frappe.whitelist()
def validate_statement(name):
    return validate_import(name)


@frappe.whitelist()
def get_statement_duplicate_review(name):
    return get_duplicate_review(name)


@frappe.whitelist()
def start_statement_import(name, review_decisions=None, expected_review_token=None):
    return start_import(
        name,
        review_decisions=review_decisions,
        expected_review_token=expected_review_token,
    )


@frappe.whitelist()
def get_status(name):
    return get_import_status(name)
