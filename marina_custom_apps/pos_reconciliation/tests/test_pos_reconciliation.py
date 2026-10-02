from unittest import TestCase

from marina_custom_apps.pos_reconciliation.doctype.bank_pos_transaction.bank_pos_transaction import (
    build_reconciliation_key,
    normalize_transaction_type,
)


class TestPOSReconciliationKey(TestCase):
    def test_purchase_key_keeps_leading_zeroes(self):
        self.assertEqual(
            build_reconciliation_key(
                "5564537642112682",
                "092239000075",
                "020291",
                "PURCHASE",
            ),
            "5564537642112682|092239000075|020291|PURCHASE",
        )

    def test_erp_purchase_code_normalizes_to_bank_value(self):
        self.assertEqual(normalize_transaction_type("PUR"), "PURCHASE")

    def test_refund_aliases_have_stable_future_key_component(self):
        self.assertEqual(normalize_transaction_type("REF"), "REFUND")
        self.assertEqual(normalize_transaction_type("RETURN"), "REFUND")
