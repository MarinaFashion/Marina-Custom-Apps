"""Unit tests for bank statement POS reconciliation detail projection."""

from unittest import TestCase
from types import SimpleNamespace

from marina_custom_apps.pos_reconciliation.statement_pos_links import (
    _canonical_details,
    _child_name,
    _chunks,
    _display_status,
)


def _row(name, status, profile):
    return SimpleNamespace(name=name, match_status=status, pos_profile=profile)


class TestStatementPOSLinks(TestCase):
    def test_display_status_labels(self):
        self.assertEqual(_display_status("Fully Matching"), "Fully Matched")
        self.assertEqual(_display_status("Bank Only - Settled"), "Bank Only - Settled")
        self.assertIsNone(_display_status("Matching Not Settled"))
        self.assertIsNone(_display_status("Discrepancy"))

    def test_one_statement_can_have_many_pos_records(self):
        settlement = {
            "transactions": [
                SimpleNamespace(reconciliation_record="PR-2", pos_profile="STORE-A"),
                SimpleNamespace(reconciliation_record="PR-1", pos_profile="STORE-A"),
            ]
        }
        lookup = {
            "PR-1": _row("PR-1", "Fully Matching", "STORE-A"),
            "PR-2": _row("PR-2", "Bank Only - Settled", "STORE-A"),
        }
        rows, profile, skipped = _canonical_details(settlement, lookup)
        self.assertEqual(rows, [
            ("PR-1", "STORE-A", "Fully Matched"),
            ("PR-2", "STORE-A", "Bank Only - Settled"),
        ])
        self.assertEqual(profile, "STORE-A")
        self.assertEqual(skipped, 0)

    def test_multiple_pos_profiles_do_not_falsely_assign_single_profile(self):
        settlement = {
            "transactions": [
                SimpleNamespace(reconciliation_record="PR-1", pos_profile="STORE-A"),
                SimpleNamespace(reconciliation_record="PR-2", pos_profile="STORE-B"),
            ]
        }
        lookup = {
            "PR-1": _row("PR-1", "Fully Matching", "STORE-A"),
            "PR-2": _row("PR-2", "Bank Only - Settled", "STORE-B"),
        }
        rows, profile, skipped = _canonical_details(settlement, lookup)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(profile)
        self.assertEqual(skipped, 0)

    def test_duplicate_settlement_child_records_are_collapsed(self):
        settlement = {
            "transactions": [
                SimpleNamespace(reconciliation_record="PR-1", pos_profile="STORE-A"),
                SimpleNamespace(reconciliation_record="PR-1", pos_profile="STORE-A"),
            ]
        }
        rows, profile, skipped = _canonical_details(
            settlement,
            {"PR-1": _row("PR-1", "Fully Matching", "STORE-A")},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(profile, "STORE-A")
        self.assertEqual(skipped, 0)

    def test_unknown_status_is_not_mislabeled_as_settled(self):
        settlement = {
            "transactions": [
                SimpleNamespace(reconciliation_record="PR-1", pos_profile="STORE-A"),
                SimpleNamespace(reconciliation_record="PR-2", pos_profile="STORE-A"),
            ]
        }
        rows, profile, skipped = _canonical_details(
            settlement,
            {
                "PR-1": _row("PR-1", "Fully Matching", "STORE-A"),
                "PR-2": _row("PR-2", "Discrepancy", "STORE-A"),
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(profile)
        self.assertEqual(skipped, 1)

    def test_statement_record_child_name_stable(self):
        first = _child_name("MBST-001", "PR-001")
        self.assertEqual(first, _child_name("MBST-001", "PR-001"))
        self.assertNotEqual(first, _child_name("MBST-001", "PR-002"))

    def test_chunks(self):
        self.assertEqual(
            [len(chunk) for chunk in _chunks(list(range(901)))],
            [400, 400, 101],
        )
