"""Focused tests for preview ledger classification; no database writes."""
import unittest
from datetime import date
from unittest.mock import patch

import frappe
from frappe import _dict

from .marina_leave_reconciliation import ledger_snapshot


class TestMarinaLeaveReconciliation(unittest.TestCase):
    @patch("frappe.get_all")
    def test_allocation_with_future_expiry_is_counted(self, fake_get_all):
        fake_get_all.return_value = [
            _dict(employee="EMP-1", transaction_type="Leave Allocation",
                  transaction_name="REAL", from_date=date(2026, 1, 1),
                  to_date=date(2026, 12, 31), leaves=30),
        ]
        result = ledger_snapshot(["EMP-1"], date(2026, 6, 1))
        self.assertEqual(float(result["EMP-1"]["credit"]), 30)

    @patch("frappe.get_all")
    def test_test_allocation_ignored(self, fake_get_all):
        fake_get_all.return_value = [
            _dict(employee="EMP-1", transaction_type="Leave Allocation",
                  transaction_name="HR-LAL-2024-00001",
                  from_date=date(2022, 1, 1), to_date=date(2024, 6, 30),
                  leaves=73),
            _dict(employee="EMP-1", transaction_type="Leave Allocation",
                  transaction_name="HR-LAL-2024-00001",
                  from_date=date(2024, 6, 30), to_date=date(2024, 6, 30),
                  leaves=-50),
        ]
        result = ledger_snapshot(["EMP-1"], date(2026, 11, 23))
        self.assertEqual(float(result["EMP-1"]["credit"]), 0)
        self.assertEqual(result["EMP-1"]["test"], 2)

    @patch("frappe.get_all")
    def test_future_and_spanning_applications_not_deducted(self, fake_get_all):
        fake_get_all.return_value = [
            _dict(employee="EMP-1", transaction_type="Leave Application",
                  transaction_name="FUTURE", from_date=date(2026, 12, 1),
                  to_date=date(2026, 12, 5), leaves=-5),
            _dict(employee="EMP-1", transaction_type="Leave Application",
                  transaction_name="SPAN", from_date=date(2026, 11, 20),
                  to_date=date(2026, 11, 30), leaves=-11),
            _dict(employee="EMP-1", transaction_type="Leave Application",
                  transaction_name="PAST", from_date=date(2026, 11, 1),
                  to_date=date(2026, 11, 10), leaves=-10),
        ]
        result = ledger_snapshot(["EMP-1"], date(2026, 11, 23))
        self.assertEqual(float(result["EMP-1"]["debit"]), -10)
        self.assertEqual(result["EMP-1"]["future"], 1)
        self.assertEqual(result["EMP-1"]["spanning"], 1)


if __name__ == "__main__":
    unittest.main()
