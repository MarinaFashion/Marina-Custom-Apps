"""Fail-safe pre-model-sync checks for the POS legacy cleanup."""

from __future__ import annotations

import frappe
from frappe import _

LEGACY_DOCTYPES = (
    "POS Bank Manual Clearance",
    "POS Bank Statement Reconciliation",
    "Marina Bank Statement Allocation",
)


def assert_legacy_tables_empty():
    for doctype in LEGACY_DOCTYPES:
        if not frappe.db.table_exists(doctype):
            continue
        if frappe.db.sql("SELECT name FROM `tab{0}` LIMIT 1".format(doctype)):
            frappe.throw(
                _("POS legacy cleanup refused: {0} still contains records. "
                  "Back up and review them before retiring this DocType.").format(doctype)
            )


def assert_no_running_pos_executions():
    if not frappe.db.table_exists("POS Reconciliation Execution"):
        return
    running = frappe.db.sql(
        """SELECT name FROM `tabPOS Reconciliation Execution`
           WHERE run_status IN ('Queued', 'Running') LIMIT 1"""
    )
    if running:
        frappe.throw(
            _("POS legacy cleanup refused: reconciliation execution {0} "
              "is still Queued/Running.").format(running[0][0])
        )


def execute():
    assert_legacy_tables_empty()
    assert_no_running_pos_executions()
