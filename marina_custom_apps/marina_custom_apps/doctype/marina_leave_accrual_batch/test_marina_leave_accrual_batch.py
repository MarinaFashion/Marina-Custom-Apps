"""Pure batch identity and snapshot tests; do not create HRMS documents."""
import unittest
from datetime import date

from .marina_leave_accrual_batch import canonical, stable_key, BLOCKERS


class TestMonthlyBatchControls(unittest.TestCase):
    def test_company_and_month_determine_unique_key(self):
        a = stable_key("Marina", date(2026, 10, 31))
        self.assertEqual(a, stable_key("Marina", date(2026, 10, 31)))
        self.assertNotEqual(a, stable_key("Other Company", date(2026, 10, 31)))
        self.assertNotEqual(a, stable_key("Marina", date(2026, 11, 30)))

    def test_material_credit_changes_snapshot(self):
        row = {
            "employee": "HR-EMP-00007", "entitlement": "Annual 30",
            "period": "2026-10", "candidate_credit": 2.776119,
            "excluded_days": 0, "status": "Ready for Approval",
            "notes": "No exceptions",
        }
        first = canonical(row)
        self.assertEqual(first, canonical(dict(row)))
        self.assertNotEqual(first, canonical({**row, "candidate_credit": 1.5}))
        self.assertNotEqual(first, canonical({**row, "excluded_days": 2}))

    def test_errors_are_not_approvable(self):
        self.assertIn("Calculation error", BLOCKERS)
        self.assertIn("No accrual for date", BLOCKERS)


if __name__ == "__main__":
    unittest.main()
