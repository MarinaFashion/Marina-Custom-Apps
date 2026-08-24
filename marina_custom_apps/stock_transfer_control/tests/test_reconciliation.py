import unittest

from marina_custom_apps.stock_transfer_control.services.reconciliation import (
    reconciliation_values,
)


class TestReconciliation(unittest.TestCase):
    def test_exact_match(self):
        values = reconciliation_values(50, 50)
        self.assertEqual(values["discrepancy_qty"], 0)
        self.assertEqual(values["posting_qty"], 50)

    def test_short_receipt(self):
        values = reconciliation_values(50, 45)
        self.assertEqual(values["discrepancy_qty"], 5)
        self.assertEqual(values["posting_qty"], 45)

    def test_over_receipt(self):
        values = reconciliation_values(50, 55)
        self.assertEqual(values["discrepancy_qty"], -5)
        self.assertEqual(values["posting_qty"], 50)

    def test_unexpected_item(self):
        values = reconciliation_values(0, 10)
        self.assertEqual(values["discrepancy_qty"], -10)
        self.assertEqual(values["posting_qty"], 0)


if __name__ == "__main__":
    unittest.main()
