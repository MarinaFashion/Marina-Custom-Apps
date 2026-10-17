"""Regression tests for short POS bank-charge Journal Entry header remarks."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from marina_custom_apps.pos_reconciliation.accounting_service import (
    _generated_posting_reference,
    _journal_entry_description,
)


def _item(name, date, profile):
    return SimpleNamespace(
        bank_transaction=name,
        transaction_date=date,
        pos_profile=profile,
    )


class TestPOSBankCommissionJournalRemarks(TestCase):
    def test_short_remark_uses_unique_transaction_and_store_counts(self):
        posting = SimpleNamespace(
            name="POS-ACC-2026-00001",
            items=[
                _item("BPT-1", "2026-09-02", "POS01"),
                _item("BPT-2", "2026-09-30", "POS02"),
                _item("BPT-2", "2026-09-30", "POS02"),
            ],
        )
        summaries = [
            SimpleNamespace(pos_profile="POS01"),
            SimpleNamespace(pos_profile="POS02"),
            SimpleNamespace(pos_profile="POS02"),
        ]
        remark = _journal_entry_description(posting, summaries)
        self.assertEqual(
            remark,
            "Recording bank commission and VAT for 2 POS transactions "
            "from 2026-09-02 to 2026-09-30 across 2 stores. "
            "Posting: POS-ACC-2026-00001",
        )
        self.assertNotIn("BPT-1", remark)
        self.assertNotIn("POS01", remark)

    def test_no_transaction_dates_is_safe(self):
        posting = SimpleNamespace(
            name="POS-ACC-2026-00002",
            items=[_item("BPT-3", None, "POS01")],
        )
        remark = _journal_entry_description(
            posting, [SimpleNamespace(pos_profile="POS01")]
        )
        self.assertIn("from — to — across 1 store", remark)

    @patch("marina_custom_apps.pos_reconciliation.accounting_service.frappe.db.get_value", return_value=None)
    def test_compact_remark_still_identifies_generated_je(self, _get_value):
        doc = SimpleNamespace(
            name="ACC-JV-0001", cheque_no="POS-ACC-2026-00001",
            user_remark=(
                "Recording bank commission and VAT for 6,053 POS transactions "
                "from 2026-09-02 to 2026-09-30 across 22 stores. "
                "Posting: POS-ACC-2026-00001"
            ),
        )
        self.assertEqual(_generated_posting_reference(doc), doc.cheque_no)

    @patch("marina_custom_apps.pos_reconciliation.accounting_service.frappe.db.get_value", return_value=None)
    def test_legacy_remark_still_identifies_generated_je(self, _get_value):
        doc = SimpleNamespace(
            name="ACC-JV-0002", cheque_no="POS-ACC-2026-00001",
            user_remark="POS bank commission and VAT posting | Posting: POS-ACC-2026-00001 | Transactions: 6053",
        )
        self.assertEqual(_generated_posting_reference(doc), doc.cheque_no)

    @patch("marina_custom_apps.pos_reconciliation.accounting_service.frappe.db.get_value", return_value=None)
    def test_unrelated_journal_not_classified_as_pos_generated(self, _get_value):
        doc = SimpleNamespace(
            name="ACC-JV-0003", cheque_no="POS-ACC-2026-00001",
            user_remark="Unrelated adjustment for POS accounts",
        )
        self.assertIsNone(_generated_posting_reference(doc))

    @patch("marina_custom_apps.pos_reconciliation.accounting_service.frappe.db.get_value", return_value=None)
    def test_mismatched_posting_reference_not_classified(self, _get_value):
        doc = SimpleNamespace(
            name="ACC-JV-0004", cheque_no="POS-ACC-2026-00001",
            user_remark=(
                "Recording bank commission and VAT for 3 POS transactions "
                "from 2026-09-02 to 2026-09-30 across 1 stores. "
                "Posting: POS-ACC-2026-00002"
            ),
        )
        self.assertIsNone(_generated_posting_reference(doc))
