"""Financially critical pure calculation tests (run with bench pytest)."""
import unittest

from marina_custom_apps.purchasing.po_receipt_variance_service import calculate, _collapse_templates, build_matrix


class TestPOReceiptDiscount(unittest.TestCase):
    def test_discount_only_units_beyond_fixed_eight_percent(self):
        row = calculate(100, 112, 40, 50)
        self.assertEqual(row["variance_qty"], 12)
        self.assertEqual(row["tolerance_qty"], 8)
        self.assertEqual(row["eligible_excess_qty"], 4)
        self.assertEqual(row["discount_value"], 80)

    def test_shortage_has_no_supplier_charge(self):
        row = calculate(100, 83, 40, 50)
        self.assertEqual(row["shortage_qty"], 17)
        self.assertEqual(row["eligible_excess_qty"], 0)
        self.assertEqual(row["discount_value"], 0)

    def test_inside_tolerance_no_discount(self):
        row = calculate(100, 108, 40, 50)
        self.assertEqual(row["eligible_excess_qty"], 0)

    def test_zero_order_has_no_division_error(self):
        row = calculate(0, 0, 40, 50)
        self.assertEqual(row["variance_pct"], 0)
        self.assertEqual(row["discount_value"], 0)

    def test_template_sums_variant_tolerance_without_offsetting_shortages(self):
        rows = []
        for item_code, ordered, received in (
            ("DESIGN-S", 50, 65),
            ("DESIGN-M", 50, 47),
        ):
            rows.append({
                "item_code": item_code, "item_template": "DESIGN",
                "item_year": "2027", "season": "Ramadan",
                "collection": "A", "currency": "SAR",
                "po_qty": ordered, "receipt_qty": received, "unit_cost": 40,
                "variant_count": 1, "po_lines": 1, "receipt_lines": 1,
                **calculate(ordered, received, 40, 50),
            })
        result = _collapse_templates(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["po_qty"], 100)
        self.assertEqual(result[0]["receipt_qty"], 112)
        self.assertEqual(result[0]["eligible_excess_qty"], 11)
        self.assertEqual(result[0]["discount_value"], 220)
        self.assertEqual(result[0]["shortage_qty"], 3)
        self.assertEqual(result[0]["tolerance_qty"], 8)

    def test_excel_round_half_up_for_variant_allowance(self):
        self.assertEqual(calculate(70, 80, 127)["tolerance_qty"], 6)
        self.assertEqual(calculate(80, 90, 127)["tolerance_qty"], 6)
        self.assertEqual(calculate(60, 68, 127)["tolerance_qty"], 5)
        self.assertEqual(calculate(70, 80, 127)["discount_value"], 254)

    def test_fixed_tolerance_and_adjustable_discount(self):
        row = calculate(100, 112, 40, 25)
        self.assertEqual(row["tolerance_qty"], 8)
        self.assertEqual(row["eligible_excess_qty"], 4)
        self.assertEqual(row["discount_value"], 40)

    def test_matrix_preserves_separate_variant_amounts(self):
        a = {"item_code": "A-S", "item_template": "A", "po_qty": 70,
             "receipt_qty": 80, "unit_cost": 127, **calculate(70, 80, 127)}
        b = {"item_code": "A-M", "item_template": "A", "po_qty": 80,
             "receipt_qty": 90, "unit_cost": 127, **calculate(80, 90, 127)}
        matrix = build_matrix([a, b], {"A-S": "S", "A-M": "M"}, {"A": "/files/a.jpg"})
        self.assertEqual(matrix[0]["image"], "/files/a.jpg")
        self.assertEqual(matrix[0]["totals"]["discount_value"], 508)
        self.assertEqual(matrix[0]["totals"]["eligible_excess_qty"], 8)

    def test_template_never_offsets_variant_excess_with_other_variant_shortage(self):
        rows = []
        for variant, ordered, received in (("SIZE-S", 100, 120), ("SIZE-M", 100, 80)):
            rows.append({
                "item_code": variant, "item_template": "STYLE-A",
                "item_year": "2027", "season": "Ramadan", "collection": "A",
                "currency": "SAR", "po_qty": ordered, "receipt_qty": received,
                "unit_cost": 40, "variant_count": 1, "po_lines": 1,
                "receipt_lines": 1, **calculate(ordered, received, 40, 50),
            })
        template = _collapse_templates(rows)[0]
        self.assertEqual(template["po_qty"], 200)
        self.assertEqual(template["receipt_qty"], 200)
        self.assertEqual(template["variance_qty"], 0)
        self.assertEqual(template["eligible_excess_qty"], 12)
        self.assertEqual(template["discount_value"], 240)


if __name__ == "__main__":
    unittest.main()
