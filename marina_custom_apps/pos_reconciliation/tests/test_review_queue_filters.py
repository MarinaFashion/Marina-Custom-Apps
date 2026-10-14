from unittest import TestCase

from marina_custom_apps.pos_reconciliation.review_service import (
    RESULT_STATUS_FILTERS,
    _settlement_sort_key,
    multi_filter_values,
)


class TestPOSReviewQueueFilters(TestCase):
    def test_bank_pending_excludes_manually_cleared(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Bank Pending"],
            {"match_status": "Bank Only", "resolution_status": "Pending"},
        )

    def test_marina_pending_is_internal_alhamrani_only_pending(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["Marina Pending"],
            {"match_status": "Alhamrani Only", "resolution_status": "Pending"},
        )

    def test_all_pending_uses_resolution_status(self):
        self.assertEqual(
            RESULT_STATUS_FILTERS["All Pending"],
            {"resolution_status": "Pending"},
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
