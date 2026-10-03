from types import SimpleNamespace
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.accounting_service import (
    ACCOUNTING_DRAFT,
    ACCOUNTING_DRAFT_REVIEW_REQUIRED,
    ACCOUNTING_NOT_ELIGIBLE,
    ACCOUNTING_NO_CHARGES,
    ACCOUNTING_PENDING,
    ACCOUNTING_POSTED,
    ACCOUNTING_REVIEW_REQUIRED,
    accounting_group_key,
    derive_accounting_status,
    is_reconciliation_confirmed,
)


class TestPOSAccountingService(TestCase):
    def test_confirmation_rule(self):
        self.assertTrue(is_reconciliation_confirmed("Matching", "Auto Cleared"))
        self.assertTrue(is_reconciliation_confirmed("Bank Only", "Manually Cleared"))
        self.assertFalse(is_reconciliation_confirmed("Bank Only", "Pending"))
        self.assertFalse(is_reconciliation_confirmed("Discrepancy", "Pending"))

    def test_accounting_status_rule(self):
        self.assertEqual(derive_accounting_status(False, 10, 1.5), ACCOUNTING_NOT_ELIGIBLE)
        self.assertEqual(derive_accounting_status(True, 10, 1.5), ACCOUNTING_PENDING)
        self.assertEqual(derive_accounting_status(True, 0, 0), ACCOUNTING_NO_CHARGES)
        self.assertEqual(
            derive_accounting_status(True, 10, 1.5, 0, has_journal_entry=True),
            ACCOUNTING_DRAFT,
        )
        self.assertEqual(
            derive_accounting_status(False, 10, 1.5, 0, has_journal_entry=True),
            ACCOUNTING_DRAFT_REVIEW_REQUIRED,
        )
        self.assertEqual(
            derive_accounting_status(True, 10, 1.5, 1, has_journal_entry=True),
            ACCOUNTING_POSTED,
        )
        self.assertEqual(
            derive_accounting_status(False, 10, 1.5, 1, has_journal_entry=True),
            ACCOUNTING_REVIEW_REQUIRED,
        )

    def test_grouping_no_longer_depends_on_settlement(self):
        a = SimpleNamespace(pos_profile="Store A")
        b = SimpleNamespace(pos_profile="Store B")
        self.assertEqual(accounting_group_key(a, True), accounting_group_key(b, True))
        self.assertNotEqual(accounting_group_key(a, False), accounting_group_key(b, False))
