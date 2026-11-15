"""Focused parser tests for Excel-paste receiving workflow."""
import unittest
from unittest.mock import patch

from marina_custom_apps.purchasing.bulk_shipment_receiving import _parse, _decisions, _evaluate


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

    def test_review_decisions(self):
        result = _decisions([
            {"item_code": "SKU-A", "decision": "Accept", "po_item": "po-item-1"},
            {"item_code": "SKU-B", "decision": "Reject"},
        ])
        self.assertEqual(result["SKU-A"]["po_item"], "po-item-1")
        self.assertEqual(result["SKU-B"]["decision"], "Reject")

    def test_duplicates_within_review_decisions_are_blocked(self):
        with self.assertRaises(Exception):
            _decisions([
                {"item_code": "SKU-A", "decision": "Accept"},
                {"item_code": "SKU-A", "decision": "Reject"},
            ])

    def test_receive_without_po_decision_is_explicit(self):
        row = _decisions([{
            "item_code": "SKU-A", "decision": "Receive Without PO",
            "rate": "12.50", "warehouse": "Stores - M"
        }])["SKU-A"]
        self.assertEqual(row["rate"], "12.50")
        self.assertEqual(row["decision"], "Receive Without PO")

    def test_invalid_review_action_rejected(self):
        with self.assertRaises(Exception):
            _decisions([{"item_code": "SKU-A", "decision": "Force PO Closed"}])

    def test_existing_variant_without_available_po_is_exception_not_invalid(self):
        with patch("marina_custom_apps.purchasing.bulk_shipment_receiving._lookup",
                   return_value=({}, {"SKU-A": "STYLE-A"})):
            rows, errors = _evaluate("SKU-A\\t6", "SUPPLIER", "COMPANY")
        self.assertFalse(errors)
        self.assertEqual(rows[0]["status"], "No Available PO")
        self.assertFalse(rows[0]["candidates"])

    def test_nonexistent_item_cannot_be_received_without_po(self):
        with patch("marina_custom_apps.purchasing.bulk_shipment_receiving._lookup",
                   return_value=({}, {})):
            rows, errors = _evaluate("BAD-SKU\\t6", "SUPPLIER", "COMPANY")
        self.assertFalse(errors)
        self.assertEqual(rows[0]["status"], "Invalid Item")

    def test_zero_qty_is_excluded(self):
        rows, errors = _parse("SKU-A\t0\nSKU-B\t1")
        self.assertFalse(errors)
        self.assertEqual(list(rows), ["SKU-B"])


if __name__ == "__main__":
    unittest.main()
