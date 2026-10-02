from types import SimpleNamespace
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.reconciliation_engine import (
    compare_transactions,
    normalize_card_type,
    normalize_masked_pan,
)


class TestPOSReconciliationEngine(TestCase):
    def test_card_type_normalization(self):
        self.assertEqual(normalize_card_type("SPAN"), "MADA")
        self.assertEqual(normalize_card_type("MASTER_CARD"), "MASTERCARD")
        self.assertEqual(normalize_card_type("MASTERCARD"), "MASTERCARD")
        self.assertEqual(normalize_card_type("VISA"), "VISA")

    def test_masked_pan_normalization(self):
        self.assertEqual(
            normalize_masked_pan("532446XXXXXX2946"),
            normalize_masked_pan("532446******2946"),
        )

    def test_matching_sample_has_no_discrepancy(self):
        bank = SimpleNamespace(
            transaction_amount=409.00,
            card_type="MASTER_CARD",
            masked_card_number="532446XXXXXX2946",
            transaction_date="2026-09-29",
            transaction_time="22:39:46",
        )
        alhamrani = SimpleNamespace(
            amount=409.00,
            card_type="MASTERCARD",
            masked_pan="532446******2946",
            transaction_date="2026-09-29",
            transaction_time="22:39:46",
        )
        self.assertEqual(compare_transactions(bank, alhamrani), [])

    def test_amount_variance_is_detected(self):
        bank = SimpleNamespace(
            transaction_amount=409.00,
            card_type="VISA",
            masked_card_number="411111XXXXXX1111",
            transaction_date="2026-09-29",
            transaction_time="22:39:46",
        )
        alhamrani = SimpleNamespace(
            amount=419.00,
            card_type="VISA",
            masked_pan="411111******1111",
            transaction_date="2026-09-29",
            transaction_time="22:39:46",
        )
        self.assertIn("Amount", compare_transactions(bank, alhamrani))
