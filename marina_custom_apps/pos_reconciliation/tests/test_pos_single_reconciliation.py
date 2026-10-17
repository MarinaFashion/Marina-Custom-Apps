from unittest import TestCase

import frappe

from marina_custom_apps.pos_reconciliation.reconciliation_engine import (
    _material_change,
    _record_key,
    _record_name,
)


class TestCanonicalPOSReconciliationKeys(TestCase):
    def test_bank_identity_does_not_depend_on_run(self):
        first = _record_key("POS-REC-2026-00001", bank_transaction="BANK-001")
        second = _record_key("POS Reconciliation Run", bank_transaction="BANK-001")
        self.assertEqual(first, second)
        self.assertEqual(_record_name(first), _record_name(second))

    def test_alhamrani_only_has_separate_identity(self):
        self.assertEqual(
            _record_key(bank_transaction="BANK-001", alhamrani_transaction="ALH-001"),
            "BANK|BANK-001",
        )
        self.assertEqual(
            _record_key(alhamrani_transaction="ALH-001"),
            "ALHAMRANI|ALH-001",
        )

    def test_reconciliation_financial_change_detected(self):
        current = frappe._dict(
            bank_transaction="BANK-001", alhamrani_transaction="ALH-001",
            match_status="Fully Matching", bank_amount=500,
            alhamrani_amount=500, bank_commission_amount=5,
            bank_commission_vat_amount=0.75,
        )
        unchanged = dict(current)
        unchanged["match_status"] = "Matching Not Settled"
        self.assertFalse(_material_change(current, unchanged))

        changed = dict(unchanged)
        changed["bank_amount"] = 600
        self.assertTrue(_material_change(current, changed))

        unmatched = dict(unchanged)
        unmatched["alhamrani_transaction"] = None
        self.assertTrue(_material_change(current, unmatched))
