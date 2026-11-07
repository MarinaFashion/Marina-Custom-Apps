"""Financially critical pure calculation tests (run with bench pytest)."""
import unittest

from marina_custom_apps.purchasing.po_receipt_variance_service import calculate


class TestPOReceiptDiscount(unittest.TestCase):
    def test_discount_only_units_beyond_five_percent(self):
        row = calculate(100, 112, 40, 5, 50)
        self.assertEqual(row["variance_qty"], 12)
        self.assertEqual(row["tolerance_qty"], 5)
        self.assertEqual(row["eligible_excess_qty"], 7)
        self.assertEqual(row["discount_value"], 140)

    def test_shortage_has_no_supplier_charge(self):
        row = calculate(100, 83, 40, 5, 50)
        self.assertEqual(row["shortage_qty"], 17)
        self.assertEqual(row["eligible_excess_qty"], 0)
        self.assertEqual(row["discount_value"], 0)

    def test_inside_tolerance_no_discount(self):
        row = calculate(100, 105, 40, 5, 50)
        self.assertEqual(row["eligible_excess_qty"], 0)

    def test_zero_order_has_no_division_error(self):
        row = calculate(0, 0, 40, 5, 50)
        self.assertEqual(row["variance_pct"], 0)
        self.assertEqual(row["discount_value"], 0)

    def test_adjustable_tolerance_and_discount(self):
        row = calculate(100, 112, 40, 10, 25)
        self.assertEqual(row["eligible_excess_qty"], 2)
        self.assertEqual(row["discount_value"], 20)


if __name__ == "__main__":
    unittest.main()
