from unittest import TestCase

from marina_custom_apps.pos_reconciliation.review_service import RESULT_STATUS_FILTERS


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
