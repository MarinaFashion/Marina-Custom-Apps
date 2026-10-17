"""Abort migration before changing the standard Run DocType into a Single."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

HISTORICAL_TABLES = (
    "POS Reconciliation Record",
    "POS Accounting Posting",
    "POS Accounting Posting Item",
    "POS Bank Settlement",
    "POS Bank Settlement Transaction",
)


def _has_rows(doctype):
    return frappe.db.table_exists(doctype) and bool(
        frappe.db.sql(f"SELECT name FROM `tab{doctype}` LIMIT 1")
    )


def _has_link(doctype, field):
    if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, field):
        return False
    return bool(
        frappe.db.sql(
            f"SELECT name FROM `tab{doctype}` WHERE COALESCE(`{field}`, '') != '' LIMIT 1"
        )
    )


def execute():
    if not frappe.db.exists("DocType", "POS Reconciliation Run"):
        return
    if cint(frappe.db.get_value("DocType", "POS Reconciliation Run", "issingle")):
        return

    occupied = [doctype for doctype in HISTORICAL_TABLES if _has_rows(doctype)]
    if occupied:
        frappe.throw(
            _("Single migration refused: existing historical documents in {0}. Backup and resolve before retrying.").format(
                ", ".join(occupied)
            )
        )

    for doctype, field in (
        ("Marina Bank Statement Transaction", "pos_reconciliation_run"),
        ("Bank POS Transaction", "accounting_posting"),
        ("Bank POS Transaction", "journal_entry"),
    ):
        if _has_link(doctype, field):
            frappe.throw(
                _("Single migration refused: {0}.{1} contains linked historical data.").format(doctype, field)
            )

    if frappe.db.table_exists("POS Reconciliation Run"):
        pending = frappe.db.sql(
            """SELECT name FROM `tabPOS Reconciliation Run`
               WHERE execution_status IN ('Queued', 'Running') LIMIT 1"""
        )
        if pending:
            frappe.throw(_("Single migration refused: an old reconciliation execution is Queued or Running."))

    # Leave the old normal-document table untouched for a manual rollback.
    # Frappe will store the new Single values in tabSingles after model sync.
