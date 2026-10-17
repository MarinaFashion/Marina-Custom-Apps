"""Safety-focused tests for the experimental Demo-only reset helper."""

from unittest import TestCase

from marina_custom_apps.pos_reconciliation import demo_bank_statement_reset as reset


class TestDemoBankStatementReset(TestCase):
    def test_chunks_bounded(self):
        values = list(range(731))
        groups = list(reset._chunks(values, 300))
        self.assertEqual([len(x) for x in groups], [300, 300, 131])
        self.assertEqual([x for group in groups for x in group], values)

    def test_empty_chunk_sequence(self):
        self.assertEqual(list(reset._chunks([])), [])

    def test_demo_only_confirmation_is_explicit(self):
        self.assertEqual(reset.SITE, "marinademo.frappe.cloud")
        self.assertEqual(reset.PHRASE, "DELETE DEMO LINKED BANK STATEMENTS")

    def test_protected_accounting_statuses(self):
        self.assertIn("Posted", reset.PROTECTED_ACCOUNTING)
        self.assertIn("Draft Created", reset.PROTECTED_ACCOUNTING)
        self.assertIn("Checked & Approved", reset.PROTECTED_REVIEW)
