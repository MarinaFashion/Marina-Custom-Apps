"""Regression tests: manually confirmed terminal slips must never auto-match.

Run within the Demo Frappe bench test environment. These tests do not write any
payment, settlement, or accounting documents.
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    is_manual_slip_confirmation,
)
from marina_custom_apps.pos_reconciliation import reconciliation_engine as engine

SERVICE = "marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service"


class TestManualResponseMeaning(TestCase):
    def test_exact_manual_response_is_recognized_with_whitespace_and_case(self):
        self.assertTrue(is_manual_slip_confirmation("Confirmed manually from terminal slip"))
        self.assertTrue(is_manual_slip_confirmation("  CONFIRMED   MANUALLY from terminal SLIP  "))

    def test_normal_approvals_are_not_marked_manual(self):
        self.assertFalse(is_manual_slip_confirmation(None))
        self.assertFalse(is_manual_slip_confirmation(""))
        self.assertFalse(is_manual_slip_confirmation("Approved"))
        self.assertFalse(is_manual_slip_confirmation("Confirmed from terminal response"))


class TestManualSlipAutoMatchGuard(TestCase):
    def setUp(self):
        self.bank = SimpleNamespace(name="BPT-TEST", reconciliation_key="T1|123456789012|ABC|PURCHASE")
        # Intentionally a complete key, simulating a bank-enriched manual slip.
        self.manual = SimpleNamespace(
            name="AUP-MANUAL", reconciliation_key=self.bank.reconciliation_key,
            manual_confirmation=True, key_error=None
        )
        self.normal = SimpleNamespace(
            name="AUP-NORMAL", reconciliation_key=self.bank.reconciliation_key,
            manual_confirmation=False, key_error=None
        )

    def _results(self, sources, approved_links=None):
        approved_links = approved_links or {}

        def fake_result(run, bank=None, alhamrani=None, card_mapper=None):
            return {
                "bank_transaction": bank.name if bank else None,
                "alhamrani_transaction": alhamrani.name if alhamrani else None,
            }

        with (
            patch.object(engine, "_base_result", side_effect=fake_result),
            patch.object(engine, "_integration_dates", return_value={}),
            patch.object(engine, "_is_before_integration", return_value=False),
            patch.object(engine, "now_datetime", return_value="2026-10-25 12:00:00"),
            patch.object(engine, "compare_transactions", return_value=[]) as compared,
            patch(f"{SERVICE}.active_manual_links", return_value=approved_links),
            patch(f"{SERVICE}.validate_manual_pair") as validated,
        ):
            results = engine._build_results(
                SimpleNamespace(name="RUN-TEST"),
                [self.bank],
                sources,
                card_mapper=object(),
            )
        return results, compared.call_count, validated.call_count

    def test_complete_key_manual_slip_remains_unmatched_without_approved_link(self):
        results, compared, validated = self._results([self.manual])
        self.assertEqual(len(results), 2)
        by_status = {row["match_status"]: row for row in results}
        self.assertIn("Bank Only - Not Settled", by_status)
        self.assertIn("Alhamrani Only", by_status)
        self.assertIn("approved link required", by_status["Alhamrani Only"]["discrepancy_fields"])
        self.assertEqual(compared, 0)
        self.assertEqual(validated, 0)

    def test_explicit_approved_manual_link_can_pair_complete_key_slip(self):
        results, compared, validated = self._results(
            [self.manual], {"BPT-TEST": "AUP-MANUAL"}
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match_status"], "Matching Not Settled")
        self.assertEqual(results[0]["alhamrani_transaction"], "AUP-MANUAL")
        self.assertEqual(compared, 0)
        self.assertEqual(validated, 1)

    def test_normal_terminal_approval_still_auto_matches(self):
        results, compared, validated = self._results([self.normal])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match_status"], "Matching Not Settled")
        self.assertEqual(results[0]["alhamrani_transaction"], "AUP-NORMAL")
        self.assertEqual(compared, 1)
        self.assertEqual(validated, 0)

    def test_manual_slip_does_not_create_duplicate_key_exception(self):
        results, compared, validated = self._results([self.manual, self.normal])
        self.assertEqual(len(results), 2)
        matched = [row for row in results if row["bank_transaction"]]
        self.assertEqual(matched[0]["alhamrani_transaction"], "AUP-NORMAL")
        self.assertEqual(matched[0]["match_status"], "Matching Not Settled")
        self.assertEqual(compared, 1)
        self.assertEqual(validated, 0)
