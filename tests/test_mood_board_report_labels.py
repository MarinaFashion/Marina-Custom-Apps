"""Display-only Mood Board labels; identifiers and stored names remain unchanged."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class MoodBoardReportLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = sys.modules.get("frappe")
        sys.modules["frappe"] = types.ModuleType("frappe")
        path = (Path(__file__).resolve().parents[1] /
                "marina_custom_apps/design_management/collection_report.py")
        spec = importlib.util.spec_from_file_location("_marina_collection_report_labels", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.previous is None:
            sys.modules.pop("frappe", None)
        else:
            sys.modules["frappe"] = cls.previous

    def test_numbered_mood_board_report(self):
        self.assertEqual(
            self.module.cover_heading("2027", "Summer", "Hajj", "Drop-01",
                                      "01-Powder Glamour"),
            "2027 / Summer / Hajj / Drop-01 / Powder Glamour",
        )

    def test_existing_unnumbered_name_unchanged(self):
        self.assertEqual(self.module.mood_board_display_name("Soft Tailoring"),
                         "Soft Tailoring")

    def test_only_leading_numeric_prefix_removed(self):
        self.assertEqual(self.module.mood_board_display_name("07-Soft Tailoring"),
                         "Soft Tailoring")
        self.assertEqual(self.module.mood_board_display_name("2027 Mood Board - 01"),
                         "2027 Mood Board - 01")
        self.assertEqual(self.module.mood_board_display_name("A01-Powder Glamour"),
                         "A01-Powder Glamour")

    def test_optional_hierarchy_fields(self):
        self.assertEqual(
            self.module.cover_heading("2027", "Summer", "", None,
                                      "02-Soft Architecture"),
            "2027 / Summer / Soft Architecture",
        )


if __name__ == "__main__":
    unittest.main()
