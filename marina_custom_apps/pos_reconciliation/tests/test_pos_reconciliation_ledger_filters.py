from unittest import TestCase

from marina_custom_apps.pos_reconciliation.review_service import (
    ACCOUNTING_ELIGIBLE_STATUSES,
    LEDGER_POSTING_STATUS_FILTERS,
)


class TestPOSReconciliationLedgerFilters(TestCase):
    def test_posted_to_ledger_excludes_drafts(self):
        self.assertEqual(
            LEDGER_POSTING_STATUS_FILTERS["Posted to Ledger"],
            ["Posted", "Posted - Review Required"],
        )

    def test_unposted_to_ledger_includes_drafts(self):
        self.assertEqual(
            LEDGER_POSTING_STATUS_FILTERS["Unposted to Ledger"],
            ["Pending Accounting", "Draft Created", "Draft - Review Required"],
        )

    def test_no_posting_required_is_no_charges(self):
        self.assertEqual(
            LEDGER_POSTING_STATUS_FILTERS["No Posting Required"],
            ["No Charges"],
        )

    def test_confirmed_no_charge_is_still_accounting_eligible(self):
        self.assertIn("No Charges", ACCOUNTING_ELIGIBLE_STATUSES)
