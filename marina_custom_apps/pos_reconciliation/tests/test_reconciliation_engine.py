from types import SimpleNamespace
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.card_type_mapping import CardTypeMapper
from marina_custom_apps.pos_reconciliation.reconciliation_engine import compare_transactions, normalize_card_type, normalize_masked_pan


class TestPOSReconciliationEngine(TestCase):
    def test_generic_card_type_normalization(self):
        self.assertEqual(normalize_card_type(" master_card "), "MASTER CARD")
        self.assertEqual(normalize_card_type("american-express"), "AMERICAN EXPRESS")

    def test_configurable_card_type_mapping(self):
        mapper = CardTypeMapper([{"bank_card_type":"AMEX","alhamrani_card_type":"AMERICAN E","unified_card_type":"AMERICAN EXPRESS"}])
        self.assertEqual(mapper.bank("AMEX"), "AMERICAN EXPRESS")
        self.assertEqual(mapper.alhamrani("AMERICAN E"), "AMERICAN EXPRESS")

    def test_masked_pan_normalization(self):
        self.assertEqual(normalize_masked_pan("532446XXXXXX2946"), normalize_masked_pan("532446******2946"))

    def test_matching_sample_has_no_discrepancy(self):
        mapper = CardTypeMapper([{"bank_card_type":"MASTER_CARD","alhamrani_card_type":"MASTERCARD","unified_card_type":"MASTERCARD"}])
        bank = SimpleNamespace(transaction_amount=409.00, card_type="MASTER_CARD", masked_card_number="532446XXXXXX2946", transaction_date="2026-09-29", transaction_time="22:39:46")
        alhamrani = SimpleNamespace(amount=409.00, card_type="MASTERCARD", masked_pan="532446******2946", transaction_date="2026-09-29", transaction_time="22:39:46")
        self.assertEqual(compare_transactions(bank, alhamrani, card_mapper=mapper), [])

    def test_amount_variance_is_detected(self):
        mapper = CardTypeMapper([{"bank_card_type":"VISA","alhamrani_card_type":"VISA","unified_card_type":"VISA"}])
        bank = SimpleNamespace(transaction_amount=409.00, card_type="VISA", masked_card_number="411111XXXXXX1111", transaction_date="2026-09-29", transaction_time="22:39:46")
        alhamrani = SimpleNamespace(amount=419.00, card_type="VISA", masked_pan="411111******1111", transaction_date="2026-09-29", transaction_time="22:39:46")
        self.assertIn("Amount", compare_transactions(bank, alhamrani, card_mapper=mapper))