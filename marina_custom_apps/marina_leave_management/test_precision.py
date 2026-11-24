"""Pure posting rounding and idempotency key tests. No HRMS mutations."""
import unittest
from decimal import Decimal

from .precision import calculate_posting, posting_key


class TestLeavePostingPrecision(unittest.TestCase):
    def test_fractional_month_and_residual(self):
        result = calculate_posting("2.776119")
        self.assertEqual(result["hrms_credit"], "2.776")
        self.assertEqual(result["closing_residual"], "0.000119")

    def test_carryover_preserves_cumulative_precision(self):
        first = calculate_posting("2.776119")
        second = calculate_posting("2.686567", first["closing_residual"])
        self.assertEqual(second["hrms_credit"], "2.687")
        self.assertEqual(second["closing_residual"], "-0.000314")
        total_posted = Decimal(first["hrms_credit"]) + Decimal(second["hrms_credit"])
        exact_total = Decimal(first["exact_credit"]) + Decimal(second["exact_credit"])
        self.assertEqual(total_posted + Decimal(second["closing_residual"]), exact_total)

    def test_zero_credit_and_residual(self):
        self.assertEqual(calculate_posting("0")["hrms_credit"], "0.000")

    def test_reject_negative_credit(self):
        with self.assertRaises(ValueError):
            calculate_posting("-1.0")

    def test_employee_month_unique_key(self):
        base = posting_key("Marina", "HR-EMP-00007", "Paid Leave", "2026-10-31")
        self.assertEqual(base, posting_key("Marina", "HR-EMP-00007", "Paid Leave", "2026-10-31"))
        self.assertNotEqual(base, posting_key("Marina", "HR-EMP-00007", "Paid Leave", "2026-11-30"))
        with self.assertRaises(ValueError):
            posting_key("Marina", "HR-EMP-00007", "Paid Leave", "2026-10-30")


if __name__ == "__main__":
    unittest.main()
