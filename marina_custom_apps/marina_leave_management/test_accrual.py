"""Pure calculation tests: run with Python unittest in an installed app environment."""
import unittest
from datetime import date
from decimal import Decimal

from marina_custom_apps.marina_leave_management.accrual import simulate


class TestMarinaLeaveAccrual(unittest.TestCase):
    def test_full_month_30_day_contract(self):
        result = simulate("2026-01-01", "Annual 30", "2026-01-31")
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(Decimal(result["earned"]), Decimal("2.727273"))
        self.assertEqual(result["rows"][0]["credit_date"], "2026-01-31")

    def test_full_month_21_day_contract(self):
        result = simulate("2026-01-01", "Annual 21", "2026-01-31")
        self.assertEqual(Decimal(result["earned"]), Decimal("1.858407"))

    def test_partial_joining_month(self):
        full = simulate("2026-01-01", "Annual 30", "2026-01-31")
        part = simulate("2026-01-16", "Annual 30", "2026-01-31")
        self.assertLess(Decimal(part["earned"]), Decimal(full["earned"]))

    def test_leave_excluded_and_overlap_not_double_counted(self):
        interval = {"from_date": "2026-01-10", "to_date": "2026-01-14"}
        one = simulate("2026-01-01", "Annual 30", "2026-01-31", [interval])
        duplicate = simulate("2026-01-01", "Annual 30", "2026-01-31",
                             [interval, interval])
        self.assertEqual(one["earned"], duplicate["earned"])
        self.assertEqual(one["excluded_days"], "5.000000")

    def test_half_day(self):
        result = simulate("2026-01-01", "Annual 21", "2026-01-31",
                          [{"from_date": "2026-01-05",
                            "to_date": "2026-01-05", "fraction": "0.5"}])
        self.assertEqual(result["excluded_days"], "0.500000")

    def test_no_current_month_credit(self):
        result = simulate("2026-01-01", "Annual 30", "2026-01-30")
        self.assertEqual(result["earned"], "0.000000")
        self.assertEqual(result["unposted_month"], "2026-01-01")

    def test_year_end_credit_posted_december_31(self):
        result = simulate("2026-01-01", "Annual 30", "2026-12-31")
        self.assertEqual(result["rows"][-1]["credit_date"], "2026-12-31")
        self.assertEqual(len(result["rows"]), 12)

    def test_first_month_partial_joining_posted_month_end(self):
        result = simulate("2026-01-16", "Annual 30", "2026-01-31")
        self.assertEqual(result["rows"][0]["credit_date"], "2026-01-31")
        self.assertGreater(Decimal(result["earned"]), Decimal("0"))

    def test_anniversary_cap(self):
        result = simulate("2025-01-15", "Annual 30", "2026-01-31")
        self.assertLessEqual(Decimal(result["earned"]), Decimal("35"))

    def test_reject_invalid_entitlement(self):
        with self.assertRaises(ValueError):
            simulate("2026-01-01", "Annual 25", "2026-01-31")


if __name__ == "__main__":
    unittest.main()
