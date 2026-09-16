import unittest
from datetime import date

from marina_custom_apps.stock_transfer_audit.audit_policy import (
    controlled_receive_issue,
    effective_audit_window,
    start_date_change_issue,
)


class AuditPolicyTests(unittest.TestCase):
    def test_period_before_cutover_is_entirely_legacy(self):
        window = effective_audit_window("2026-09-01", "2026-09-15", "2026-09-16")
        self.assertIsNone(window["effective_from"])
        self.assertEqual(window["legacy_from"], date(2026, 9, 1))
        self.assertEqual(window["legacy_to"], date(2026, 9, 15))

    def test_period_crossing_cutover_is_split(self):
        window = effective_audit_window("2026-09-01", "2026-09-30", "2026-09-16")
        self.assertEqual(window["legacy_to"], date(2026, 9, 15))
        self.assertEqual(window["effective_from"], date(2026, 9, 16))
        self.assertEqual(window["effective_to"], date(2026, 9, 30))

    def test_period_after_cutover_has_no_legacy_window(self):
        window = effective_audit_window("2026-09-16", "2026-09-30", "2026-09-16")
        self.assertIsNone(window["legacy_from"])
        self.assertEqual(window["effective_from"], date(2026, 9, 16))

    def test_controlled_receive_requires_both_indicators(self):
        self.assertIsNone(controlled_receive_issue(1, "Normal Receiving"))
        self.assertIsNone(controlled_receive_issue(1, "Manual / Barcode Receiving"))
        self.assertEqual(
            controlled_receive_issue(0, "Normal Receiving"),
            "not created through End Transit",
        )
        self.assertEqual(
            controlled_receive_issue(1, ""),
            "Receiving Method is missing",
        )

    def test_start_date_cannot_move_back_after_audit_records_exist(self):
        self.assertIsNotNone(
            start_date_change_issue("2026-09-16", "2026-09-15", True)
        )
        self.assertIsNone(
            start_date_change_issue("2026-09-16", "2026-09-15", False)
        )
        self.assertIsNone(
            start_date_change_issue("2026-09-16", "2026-09-17", True)
        )


if __name__ == "__main__":
    unittest.main()
