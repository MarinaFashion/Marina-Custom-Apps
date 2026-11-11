"""Protect Season/Collection/Drop filtering across Marina Design Management UI."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
MOOD = ROOT / "marina_design_management/doctype/mood_board/mood_board.json"
DOC = ROOT / "marina_design_management/doctype/design_document/design_document.json"
REPORT = ROOT / "marina_design_management/report/mood_board_overview/mood_board_overview.js"
REPORT_API = ROOT / "design_management/collection_report.py"
REPORT_PY = ROOT / "marina_design_management/report/mood_board_overview/mood_board_overview.py"
DASHBOARD = ROOT / "marina_design_management/page/design_management_dashboard/design_management_dashboard.js"
GRID = ROOT / "marina_design_management/page/design_followup_grid/design_followup_grid.js"
GRID_API = ROOT / "design_management/clean_milestones/api.py"
DISCUSSIONS = ROOT / "marina_design_management/page/design_discussions/design_discussions.js"
COMM = ROOT / "marina_design_management/page/design_communication_center/design_communication_center.js"
DISCUSSION_API = ROOT / "design_management/discussion_center.py"

EXPECTED = {
    "season": ["Ramadan", "Summer", "Winter"],
    "collection": ["EID", "Ramadan", "Hajj", "Summer", "Autumn", "Winter"],
    "drop": ["Drop- 01", "Drop- 02", "Drop- 03", "Drop- 04",
             "Drop- B2S", "Drop- Reorder", "Not Assigned"],
}


class HierarchyFilterConsistencyTests(unittest.TestCase):
    def test_mood_board_master_options(self):
        fields = {f["fieldname"]: f for f in json.loads(MOOD.read_text())["fields"]}
        for field, values in EXPECTED.items():
            self.assertEqual(fields[field]["fieldtype"], "Select")
            self.assertEqual(fields[field]["options"].splitlines(),
                                 values if field == "drop" else [""] + values)

    def test_overview_report_options_and_drop_wiring(self):
        code = REPORT.read_text()
        for field in EXPECTED:
            self.assertIn('fieldname: "' + field + '"', code)
            self.assertIn('"year", "season", "collection", "drop"', code)
        for value in EXPECTED["drop"]:
            self.assertIn(value, code)
        self.assertIn("drop=None", REPORT_API.read_text())
        self.assertIn('("drop", drop)', REPORT_API.read_text())
        self.assertIn("'drop', 'mood_boards'", REPORT_PY.read_text())

    def test_dashboard_and_grid_filter_controls(self):
        dash = DASHBOARD.read_text()
        grid = GRID.read_text()
        for field in EXPECTED:
            self.assertIn('dropdown("' + field + '"', dash)
            self.assertIn("hierarchyFilters." + field + ".val()", grid)
        self.assertIn("season=None, collection=None, drop=None", GRID_API.read_text())

    def test_discussion_and_communication_dropdowns(self):
        for path in (DISCUSSIONS, COMM):
            with self.subTest(path=str(path)):
                code = path.read_text()
                self.assertIn("hierarchyOptions", code)
                self.assertIn("['drop','Drop']", code)
                self.assertIn("<select class=\"form-control input-sm\">", code)
        api = DISCUSSION_API.read_text()
        self.assertIn("drop=None", api)
        self.assertIn('("drop", drop)', api)

    def test_design_document_search_filters(self):
        fields = {f["fieldname"]: f for f in json.loads(DOC.read_text())["fields"]}
        for field in ("season", "collection"):
            f = fields["filter_" + field]
            self.assertEqual(f["fieldtype"], "Select")
            self.assertEqual(f["options"].splitlines()[1:], EXPECTED[field])


if __name__ == "__main__":
    unittest.main()
