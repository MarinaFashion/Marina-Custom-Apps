"""Focused parser tests for Excel-paste receiving workflow."""
import unittest

from marina_custom_apps.purchasing.bulk_shipment_receiving import _parse


class TestBulkShipmentPaste(unittest.TestCase):
    def test_excel_tab_separated_with_header(self):
        rows, errors = _parse("Item Code\tQty\nSKU-A\t2\nSKU-B\t3.5")
        self.assertFalse(errors)
        self.assertEqual(float(rows["SKU-A"]), 2.0)
        self.assertEqual(float(rows["SKU-B"]), 3.5)

    def test_duplicate_codes_aggregate(self):
        rows, errors = _parse("SKU-A\t2\nSKU-A\t1")
        self.assertFalse(errors)
        self.assertEqual(float(rows["SKU-A"]), 3.0)

    def test_negative_and_bad_quantity_are_rejected(self):
        rows, errors = _parse("SKU-A\t-4\nSKU-B\twrong\nSKU-C\t2")
        self.assertEqual(len(errors), 2)
        self.assertEqual(list(rows.keys()), ["SKU-C"])

    def test_zero_qty_is_excluded(self):
        rows, errors = _parse("SKU-A\t0\nSKU-B\t1")
        self.assertFalse(errors)
        self.assertEqual(list(rows), ["SKU-B"])


if __name__ == "__main__":
    unittest.main()
