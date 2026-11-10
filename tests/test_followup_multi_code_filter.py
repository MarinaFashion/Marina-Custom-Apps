"""Pure exact multi-Design Code filter tests: no Frappe site required."""
import unittest

from marina_custom_apps.design_management.clean_milestones.design_code_filter import (
    parse_design_codes, restrict_to_design_codes,
)


class MultiCodeFilterTests(unittest.TestCase):
    def test_json_and_deduplication(self):
        self.assertEqual(
            parse_design_codes('["S27-H-001D","S27-H-001D","S27-R-006S"]'),
            ["S27-H-001D", "S27-R-006S"],
        )

    def test_empty_unset_preserves_existing_search(self):
        self.assertEqual(parse_design_codes(None), [])
        self.assertEqual(parse_design_codes(""), [])
        original = {"factory": "Midmak"}
        self.assertTrue(restrict_to_design_codes(original, []))
        self.assertEqual(original, {"factory": "Midmak"})

    def test_exact_codes_without_existing_restriction(self):
        filters = {"mood_board": "01-Powder Glamour"}
        self.assertTrue(restrict_to_design_codes(
            filters, ["S27-H-001D", "S27-H-003D"]))
        self.assertEqual(filters["name"], ["in", ["S27-H-001D", "S27-H-003D"]])
        self.assertEqual(filters["mood_board"], "01-Powder Glamour")

    def test_custody_intersection_does_not_expand_scope(self):
        filters = {"name": ["in", ["S27-H-001D", "S27-H-003D"]]}
        self.assertTrue(restrict_to_design_codes(
            filters, ["S27-H-003D", "S27-R-006S"]))
        self.assertEqual(filters["name"], ["in", ["S27-H-003D"]])
        self.assertFalse(restrict_to_design_codes(
            {"name": ["in", ["S27-H-001D"]]}, ["S27-R-006S"]))

    def test_invalid_request_rejected(self):
        for value in (
            "not-json", "{}", "[]", '[""]', '[" S27-H-001D"]',
            '["S27 H 001D"]', [1], ["x" * 141], ["x"] * 501,
        ):
            with self.subTest(value=str(value)[:30]):
                with self.assertRaises(ValueError):
                    parse_design_codes(value)

    def test_five_hundred_is_allowed(self):
        self.assertEqual(
            len(parse_design_codes(["S27-%03d" % i for i in range(500)])), 500
        )


if __name__ == "__main__":
    unittest.main()
