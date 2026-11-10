"""Guard against forgetting the public API forwarding for multi-code filters."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "marina_custom_apps/design_management/clean_milestones/api.py"
GRID = ROOT / "marina_custom_apps/design_management/clean_milestones/grid.py"
UI = ROOT / "marina_custom_apps/marina_design_management/page/design_followup_grid/design_followup_grid.js"


class FollowupMultiCodeWiringTests(unittest.TestCase):
    def test_api_accepts_and_forwards_codes(self):
        tree = ast.parse(API.read_text(encoding="utf-8"))
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "followup_grid")
        self.assertIn("design_codes", [a.arg for a in method.args.args])
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "get_grid")
        forwarded = next((k.value for k in call.keywords
                          if k.arg == "design_codes"), None)
        self.assertIsInstance(forwarded, ast.Name)
        self.assertEqual(forwarded.id, "design_codes")

    def test_grid_intersects_selection_before_query(self):
        tree = ast.parse(GRID.read_text(encoding="utf-8"))
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "get_grid")
        source = ast.get_source_segment(GRID.read_text(encoding="utf-8"), method)
        self.assertLess(source.index("restrict_to_design_codes(filters, selected_codes)"),
                        source.index('design_query("Design Code"'))

    def test_ui_sends_codes(self):
        self.assertIn("design_codes:state.designCodes.length",
                      UI.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
