from unittest import TestCase

from marina_custom_apps.pos_reconciliation.review_service import (
    RESULT_STATUS_FILTERS,
    _settlement_sort_key,
    multi_filter_values,
)


class TestPOSReviewQueueFilters(TestCase):
    def test_bank_only_settled_is_explicit_queue(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Bank Only - Settled"],
            {"match_status": "Bank Only - Settled"},
        )

    def test_bank_only_not_settled_is_explicit_queue(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Bank Only - Not Settled"],
            {"match_status": "Bank Only - Not Settled"},
        )

    def test_alhamrani_only_is_explicit_queue(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Alhamrani Only"],
            {"match_status": "Alhamrani Only"},
        )

    def test_all_pending_uses_resolution_status(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["All Pending"],
            {"resolution_status": "Pending"},
        )

    def test_backward_bank_pending_alias_covers_both_bank_only_states(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Bank Pending"],
            {
                "match_status": [
                    "in",
                    ["Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"],
                ],
                "resolution_status": "Pending",
            },
        )

    def test_multi_filter_values_accepts_scalar_list_and_json(self):
        self.assertEqual(multi_filter_values("263"), ["263"])
        self.assertEqual(multi_filter_values(["263", "264"]), ["263", "264"])
        self.assertEqual(multi_filter_values('["263", "264"]'), ["263", "264"])

    def test_settlement_numbers_sort_numerically_without_schema_change(self):
        values = ["100", "11", "2", "001", "20"]
        self.assertEqual(
            sorted(values, key=_settlement_sort_key),
            ["001", "2", "11", "20", "100"],
        )
