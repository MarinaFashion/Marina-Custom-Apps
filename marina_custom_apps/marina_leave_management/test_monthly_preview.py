"""Month-end preview validation; no database or ledger writes."""
import unittest
from unittest.mock import patch

from marina_custom_apps.marina_leave_management.monthly_preview import (
    select_month_credit, validate_credit_date,
)


class TestMonthlyPreview(unittest.TestCase):
    @patch("marina_custom_apps.marina_leave_management.monthly_preview.today",
           return_value="2027-01-15")
    def test_december_close_is_valid(self, _):
        self.assertEqual(str(validate_credit_date("2026-12-31")), "2026-12-31")

    @patch("marina_custom_apps.marina_leave_management.monthly_preview.today",
           return_value="2027-01-15")
    def test_reject_non_month_end(self, _):
        with self.assertRaises(ValueError):
            validate_credit_date("2026-12-30")

    @patch("marina_custom_apps.marina_leave_management.monthly_preview.today",
           return_value="2027-01-15")
    def test_reject_future_month_end(self, _):
        with self.assertRaises(ValueError):
            validate_credit_date("2027-01-31")

    def test_selected_month_credit(self):
        simulation = {
            "rows": [
                {"credit_date": "2026-11-30", "earned": "2.727273"},
                {"credit_date": "2026-12-31", "earned": "2.727273"},
            ]
        }
        self.assertEqual(
            select_month_credit(simulation, "2026-12-31")["earned"],
            "2.727273",
        )


if __name__ == "__main__":
    unittest.main()
