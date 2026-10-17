"""Dashboard Match % must reflect the same cleared population as the Cleared card."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from marina_custom_apps.pos_reconciliation.dashboard_cards import get_match_percent_card


class TestPOSReconciliationClearancePercent(TestCase):
    @patch("marina_custom_apps.pos_reconciliation.dashboard_cards._reconciliation_status_summary")
    def test_counts_all_cleared_records(self, summary):
        summary.return_value = SimpleNamespace(
            total_records=8223,
            cleared_records=8061,
            matching_records=914,
        )
        result = get_match_percent_card()
        self.assertEqual(result["fieldtype"], "Percent")
        self.assertEqual(result["value"], 98.03)
        self.assertEqual(result["route"], ["List", "POS Reconciliation Record"])
        self.assertEqual(result["route_options"], {
            "resolution_status": ["in", ["Auto Cleared", "Manually Cleared"]]
        })

    @patch("marina_custom_apps.pos_reconciliation.dashboard_cards._reconciliation_status_summary")
    def test_zero_total_is_safe(self, summary):
        summary.return_value = SimpleNamespace(
            total_records=0, cleared_records=0, matching_records=0,
        )
        self.assertEqual(get_match_percent_card()["value"], 0)

    @patch("marina_custom_apps.pos_reconciliation.dashboard_cards._reconciliation_status_summary")
    def test_full_clearance_is_100_percent(self, summary):
        summary.return_value = SimpleNamespace(
            total_records=5, cleared_records=5, matching_records=0,
        )
        self.assertEqual(get_match_percent_card()["value"], 100)
