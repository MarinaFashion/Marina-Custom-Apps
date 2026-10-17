from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from marina_custom_apps.pos_reconciliation import demo_reconciliation_cleanup as cleanup


class TestDemoReconciliationCleanupGuards(TestCase):
    @patch.object(cleanup.frappe.db, "exists", return_value=None)
    @patch.object(cleanup.frappe.db, "count", return_value=0)
    @patch.object(cleanup, "_linked", return_value=False)
    def test_preview_blockers_clear_when_no_accounting_or_source_links(self, *_):
        self.assertEqual(cleanup._blockers([], [], [], []), [])

    @patch.object(cleanup.frappe.db, "exists", return_value=None)
    @patch.object(cleanup.frappe.db, "count", return_value=0)
    @patch.object(cleanup, "_linked", return_value=False)
    def test_never_clear_accounting_postings(self, *_):
        self.assertTrue(cleanup._blockers([], [], [], [SimpleNamespace(name="TEST-POSTING")]))

    @patch.object(cleanup.frappe.db, "exists", return_value=None)
    @patch.object(cleanup.frappe.db, "count", return_value=0)
    @patch.object(cleanup, "_linked", return_value=False)
    def test_never_clear_non_pos_statement_links(self, *_):
        statement = SimpleNamespace(
            name="BANK-STMT-001", is_pos_statement_line=0,
            bank_statement_reconciliation_match=None,
            reconciliation_status="Reconciled",
            pos_bank_settlement="SETTLEMENT-001",
        )
        settlement = SimpleNamespace(name="SETTLEMENT-001")
        self.assertTrue(cleanup._blockers([statement], [settlement], [], []))

    @patch.object(cleanup.frappe.db, "exists", return_value=None)
    @patch.object(cleanup.frappe.db, "count", return_value=0)
    @patch.object(cleanup, "_linked", return_value=False)
    def test_never_clear_reviewed_source_that_contains_posting_link(self, *_):
        record = SimpleNamespace(
            name="REC-001", journal_entry="JV-001",
            accounting_posting=None, accounting_status="Posted",
        )
        self.assertTrue(cleanup._blockers([], [], [record], []))
