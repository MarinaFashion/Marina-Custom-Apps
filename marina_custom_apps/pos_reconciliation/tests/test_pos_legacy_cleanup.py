"""Regression tests for migration guards and active POS/general-bank metadata."""

import inspect
import json
import os
from unittest import TestCase
from unittest.mock import patch

import frappe

from marina_custom_apps.patches.v0_53_2 import (
    preflight_legacy_cleanup as preflight,
    retire_legacy_doctypes as retire,
)
from marina_custom_apps.pos_reconciliation import reconciliation_engine


class TestPOSLegacyCleanup(TestCase):
    def test_only_three_empty_legacy_doctypes_are_targets(self):
        self.assertEqual(set(preflight.LEGACY_DOCTYPES), {
            "POS Bank Manual Clearance",
            "POS Bank Statement Reconciliation",
            "Marina Bank Statement Allocation",
        })
        self.assertNotIn("Bank Statement Reconciliation", preflight.LEGACY_DOCTYPES)
        self.assertNotIn("POS Bank Settlement", preflight.LEGACY_DOCTYPES)

    def test_nonempty_table_blocks_migration(self):
        with patch.object(preflight.frappe.db, "table_exists", return_value=True):
            with patch.object(preflight.frappe.db, "sql", return_value=[("OLD",)]):
                with self.assertRaises(frappe.ValidationError):
                    preflight.assert_legacy_tables_empty()

    def test_missing_table_is_safe(self):
        with patch.object(preflight.frappe.db, "table_exists", return_value=False):
            preflight.assert_legacy_tables_empty()

    def test_queued_or_running_job_blocks_migration(self):
        with patch.object(preflight.frappe.db, "table_exists", return_value=True):
            with patch.object(preflight.frappe.db, "sql", return_value=[("POS-EXE-1",)]):
                with self.assertRaises(frappe.ValidationError):
                    preflight.assert_no_running_pos_executions()

    def test_post_sync_rechecks_safety_before_delete(self):
        source = inspect.getsource(retire.execute)
        self.assertLess(source.index("assert_legacy_tables_empty()"), source.index("frappe.delete_doc("))
        self.assertLess(source.index("_assert_no_schema_links()"), source.index("frappe.delete_doc("))

    def test_reconciliation_engine_does_not_read_deleted_clearances(self):
        source = inspect.getsource(reconciliation_engine._build_results)
        self.assertNotIn("_bank_review_states", source)
        self.assertNotIn("_apply_bank_review", source)

    def test_bank_statement_source_has_no_unused_allocations_table(self):
        root = frappe.get_app_path("marina_custom_apps")
        path = os.path.join(
            root, "pos_reconciliation", "doctype",
            "marina_bank_statement_transaction", "marina_bank_statement_transaction.json",
        )
        with open(path, encoding="utf-8") as file:
            doc = json.load(file)
        self.assertNotIn("allocations", doc["field_order"])
        self.assertNotIn("allocations_section", doc["field_order"])
        self.assertFalse(any(row.get("fieldname") == "allocations" for row in doc["fields"]))

    def test_general_bank_reconciliation_is_preserved(self):
        root = frappe.get_app_path("marina_custom_apps")
        path = os.path.join(
            root, "pos_reconciliation", "workspace",
            "pos_reconciliation", "pos_reconciliation.json",
        )
        with open(path, encoding="utf-8") as file:
            workspace = json.load(file)
        general = [
            item for item in workspace["shortcuts"]
            if item.get("link_to") == "Bank Statement Reconciliation"
        ]
        self.assertEqual(len(general), 1)
        self.assertEqual(general[0]["doc_view"], "")
