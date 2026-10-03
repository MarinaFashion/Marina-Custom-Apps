from types import SimpleNamespace
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.reconciliation_engine import (
    compare_transactions,
    get_pan_validation_method,
)


class TestFinanceReviewFoundation(TestCase):
    def test_pan_falls_back_to_emv_last4(self):
        bank = SimpleNamespace(
            transaction_amount=280.00,
            card_type="SPAN",
            masked_card_number="529415XXXXXX8163",
            transaction_date="2026-09-30",
            transaction_time="22:49:00",
        )
        alhamrani = SimpleNamespace(
            amount=280.00,
            card_type="SPAN",
            masked_pan="506968******4337",
            emv_last4="8163",
            transaction_date="2026-09-30",
            transaction_time="22:49:00",
        )
        self.assertEqual(get_pan_validation_method(bank, alhamrani), "EMV Last 4")
        self.assertNotIn("Masked PAN", compare_transactions(bank, alhamrani))

    def test_pan_is_discrepancy_when_direct_and_emv_do_not_match(self):
        bank = SimpleNamespace(
            transaction_amount=280.00,
            card_type="SPAN",
            masked_card_number="529415XXXXXX8163",
            transaction_date="2026-09-30",
            transaction_time="22:49:00",
        )
        alhamrani = SimpleNamespace(
            amount=280.00,
            card_type="SPAN",
            masked_pan="506968******4337",
            emv_last4="9999",
            transaction_date="2026-09-30",
            transaction_time="22:49:00",
        )
        self.assertIn("Masked PAN", compare_transactions(bank, alhamrani))
