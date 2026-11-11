"""Follow-Up Grid Milestone Type dropdown and pre-pagination filtering."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
GRID_JS = ROOT / "marina_design_management/page/design_followup_grid/design_followup_grid.js"
GRID_PY = ROOT / "design_management/clean_milestones/grid.py"
API = ROOT / "design_management/clean_milestones/api.py"


class FollowupMilestoneTypeFilterTests(unittest.TestCase):
    def test_layout_and_controls(self):
        js = GRID_JS.read_text(encoding="utf-8")
        self.assertLess(js.index('filterColumn(__("Custody")'),
                        js.index('filterColumn(__("Mood Board")'))
        self.assertLess(js.index('filterColumn(__("Designer")'),
                        js.index('filterColumn(__("Milestone Type")'))
        self.assertLess(js.index('filterColumn(__("Milestone Type")'),
                        js.index('filterColumn(__("Group By")'))
        self.assertNotIn("hierarchyFilters.drop", js)
        self.assertIn('milestone_type:milestoneType.val()', js)
        self.assertIn("followup_milestone_types", js)
        self.assertIn("row.milestone_type===state.selectedMilestone", js)
        self.assertIn("state.selectedMilestone=args.milestone_type", js)

    def test_api_and_grid_signatures(self):
        api = API.read_text(encoding="utf-8")
        grid = GRID_PY.read_text(encoding="utf-8")
        ast.parse(api)
        ast.parse(grid)
        self.assertIn("def followup_milestone_types():", api)
        self.assertIn("milestone_type=milestone_type", api)
        self.assertIn("current_milestone=None, milestone_type=None", grid)

    def test_server_filters_before_pagination(self):
        grid = GRID_PY.read_text(encoding="utf-8")
        self.assertLess(grid.index("if milestone_type:"),
                        grid.index("designs = design_query("))
        self.assertIn("SELECT DISTINCT design_code", grid)
        self.assertIn('"active": "Active", "completed": "Completed", "future": "Planned"', grid)
        self.assertIn('matching_names &= set(filters["name"][1])', grid)


if __name__ == "__main__":
    unittest.main()
