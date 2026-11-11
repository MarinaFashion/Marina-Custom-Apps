"""Static regression checks for dashboard -> grid milestone drilldown wiring."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "marina_custom_apps"
DASHBOARD = BASE / "marina_design_management/page/design_management_dashboard/design_management_dashboard.js"
GRID_JS = BASE / "marina_design_management/page/design_followup_grid/design_followup_grid.js"
API = BASE / "design_management/clean_milestones/api.py"
GRID_PY = BASE / "design_management/clean_milestones/grid.py"


class DashboardDrilldownWiringTests(unittest.TestCase):
    def test_dashboard_links_two_states(self):
        source = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("mdm-milestone-drilldown", source)
        self.assertIn('"active");', source)
        self.assertIn('"completed");', source)
        self.assertIn('frappe.set_route("design-followup-grid","dashboard"', source)
        self.assertIn('"current_milestone"', source)

    def test_grid_keeps_route_filter(self):
        source = GRID_JS.read_text(encoding="utf-8")
        self.assertIn('if(selected==="dashboard")', source)
        self.assertIn('dashboard_milestone:state.dashboard?.milestone', source)
        self.assertIn('row.milestone_type===state.dashboard.milestone', source)
        self.assertIn('milestoneFilter.val(view).prop("disabled",true)', source)
        self.assertIn('Clear Dashboard Filter', source)

    def test_endpoint_passes_to_server(self):
        tree = ast.parse(API.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "followup_grid")
        names = {arg.arg for arg in function.args.args}
        for expected in ("dashboard_milestone", "year", "season", "collection",
                         "drop", "assigned_merchandiser", "deadline_status",
                         "current_milestone"):
            self.assertIn(expected, names)
        call = next(n for n in ast.walk(function) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "get_grid")
        self.assertIn("dashboard_milestone", {arg.arg for arg in call.keywords})

    def test_grid_filters_before_pagination(self):
        source = GRID_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "get_grid")
        method = ast.get_source_segment(source, function)
        self.assertLess(method.index("if dashboard_milestone:\n"),
                        method.index('design_query("Design Code"'))
        self.assertIn("p.plan_state=%s", method)
        self.assertIn("x.status!='Completed'", method)
        self.assertIn("x.status='Completed'", method)
        self.assertIn("frappe.get_list if dashboard_milestone", method)


if __name__ == "__main__":
    unittest.main()
