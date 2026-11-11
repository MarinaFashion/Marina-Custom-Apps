"""Controlled Mood Board hierarchy options: no implicit data migration."""
import json
import unittest
from pathlib import Path

DOC = (Path(__file__).resolve().parents[1] / "marina_custom_apps"
       / "marina_design_management/doctype/mood_board/mood_board.json")
DESIGN = (Path(__file__).resolve().parents[1] / "marina_custom_apps"
          / "marina_design_management/doctype/design_code/design_code.json")


class MoodBoardHierarchyOptionsTest(unittest.TestCase):
    def test_curated_options(self):
        fields = {r["fieldname"]: r for r in json.loads(DOC.read_text())["fields"]}
        expected = {
            "season": ["Ramadan", "Summer", "Winter"],
            "collection": ["EID", "Ramadan", "Hajj", "Summer", "Autumn", "Winter"],
            "drop": ["Drop- 01", "Drop- 02", "Drop- 03", "Drop- 04",
                     "Drop- B2S", "Drop- Reorder", "Not Assigned"],
        }
        for key, values in expected.items():
            with self.subTest(key=key):
                self.assertEqual(fields[key]["fieldtype"], "Select")
                self.assertEqual([x for x in fields[key]["options"].splitlines() if x], values)
        self.assertEqual(fields["drop"]["default"], "Not Assigned")
        self.assertEqual(fields["drop"]["reqd"], 1)
        self.assertEqual(fields["drop"]["options"].splitlines()[0], "Drop- 01")

    def test_design_code_hierarchy_remains_inherited(self):
        fields = {r["fieldname"]: r for r in json.loads(DESIGN.read_text())["fields"]}
        for key in ("season", "collection", "drop"):
            with self.subTest(key=key):
                self.assertEqual(fields[key]["fieldtype"], "Data")
                self.assertEqual(fields[key]["read_only"], 1)


if __name__ == "__main__":
    unittest.main()
