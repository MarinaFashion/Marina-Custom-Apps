"""Safety regressions for archiving skipped v0.53.7 legacy statement runs."""

import inspect
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from marina_custom_apps.patches.v0_53_3 import finalize_legacy_cleanup as cleanup


class TestLegacyArchiveFinalization(TestCase):
    def test_three_legacy_targets_only(self):
        self.assertEqual(set(cleanup.LEGACY_DOCTYPES), {
            "POS Bank Manual Clearance",
            "POS Bank Statement Reconciliation",
            "Marina Bank Statement Allocation",
        })
        self.assertNotIn("Bank Statement Reconciliation", cleanup.LEGACY_DOCTYPES)
        self.assertNotIn("POS Bank Settlement", cleanup.LEGACY_DOCTYPES)

    def test_empty_archive_needs_no_file(self):
        self.assertIsNone(cleanup._archive_old_statement_runs([]))

    def test_too_many_history_rows_are_rejected(self):
        rows = [frappe._dict(name=f"OLD-{i}") for i in range(11)]
        with self.assertRaises(frappe.ValidationError):
            cleanup._archive_old_statement_runs(rows)

    @patch.object(cleanup.frappe.db, "table_exists", return_value=True)
    @patch.object(cleanup.frappe.db, "sql", return_value=[("LINKED",)])
    def test_a_live_reference_blocks_cleanup(self, _query, _table):
        with self.assertRaises(frappe.ValidationError):
            cleanup._assert_unlinked([frappe._dict(name="POS-BANK-REC-OLD")])

    def test_table_cleanup_has_archive_before_drop(self):
        source = inspect.getsource(cleanup.execute)
        self.assertLess(
            source.index("_archive_old_statement_runs("),
            source.index("DROP TABLE"),
        )
        self.assertLess(
            source.index("assert_no_running_pos_executions()"),
            source.index("DROP TABLE"),
        )
        self.assertLess(
            source.index("_assert_no_schema_links()"),
            source.index("DROP TABLE"),
        )

    @patch.object(cleanup, "_assert_unlinked")
    @patch.object(cleanup.frappe.db, "exists", return_value=True)
    @patch.object(cleanup.frappe, "get_doc")
    @patch.object(cleanup.frappe, "get_all", return_value=[])
    @patch.object(cleanup.frappe, "as_json", return_value='{"archived":true}')
    def test_file_archive_is_private_and_verified(
        self, _json, _files, get_doc, _exists, _links
    ):
        doc = Mock()
        doc.name = "FILE-ARCHIVE-1"
        doc.get_content.return_value = b'{"archived":true}'
        get_doc.return_value = doc
        with patch("frappe.utils.file_manager.save_file", return_value=doc) as save:
            name = cleanup._archive_old_statement_runs([
                frappe._dict(name="POS-BANK-REC-2026-00001", status="Completed")
            ])
        self.assertEqual(name, "FILE-ARCHIVE-1")
        self.assertEqual(save.call_args.kwargs["is_private"], 1)
        self.assertEqual(save.call_args.args[2], "POS Reconciliation Run")
        self.assertEqual(save.call_args.args[3], "POS Reconciliation Run")

    @patch.object(cleanup, "_assert_unlinked")
    @patch.object(cleanup.frappe.db, "exists", return_value=True)
    @patch.object(cleanup.frappe, "get_doc")
    @patch.object(cleanup.frappe, "get_all", return_value=[])
    @patch.object(cleanup.frappe, "as_json", return_value='{"archived":true}')
    def test_archive_corruption_blocks_cleanup(
        self, _json, _files, get_doc, _exists, _links
    ):
        doc = Mock()
        doc.name = "FILE-ARCHIVE-1"
        doc.get_content.return_value = b"incorrect"
        get_doc.return_value = doc
        with patch("frappe.utils.file_manager.save_file", return_value=doc):
            with self.assertRaises(frappe.ValidationError):
                cleanup._archive_old_statement_runs([
                    frappe._dict(name="POS-BANK-REC-2026-00001")
                ])
