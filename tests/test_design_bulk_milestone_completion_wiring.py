"""Regression guard for bulk completion reusing the single-design workflow."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
BULK = ROOT / "design_management/clean_milestones/bulk_completion.py"
API = ROOT / "design_management/clean_milestones/api.py"
GRID = ROOT / "marina_design_management/page/design_followup_grid/design_followup_grid.js"


def function(name):
    module = ast.parse(BULK.read_text(encoding="utf-8"))
    return next(node for node in module.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


class BulkMilestoneCompletionWiringTests(unittest.TestCase):
    def test_single_workflow_is_reused(self):
        node = function("complete_bulk")
        code = ast.get_source_segment(BULK.read_text(encoding="utf-8"), node)
        self.assertIn("service.advance(", code)
        self.assertIn('"Completed"', code)
        self.assertIn("service._lock_design(code)", code)
        self.assertIn("rows = _inspect(parsed, reason=reason)", code)
        self.assertNotIn("frappe.db.commit(", code)
        self.assertNotIn("frappe.db.set_value(", code)

    def test_selection_same_milestone_step_custodian(self):
        code = BULK.read_text(encoding="utf-8")
        self.assertIn("MAX_BULK = 50", code)
        self.assertIn("return sorted(parsed)", code)
        self.assertIn("(row.milestone_type, row.status, row.current_custodian)", code)
        self.assertIn('if "Completed" not in allowed:', code)
        self.assertIn("service._authorize(", code)
        self.assertIn("service._role_user(", code)
        self.assertIn("len(required_types) != 1", code)

    def test_evidence_linking_uses_published_document_rules(self):
        code = BULK.read_text(encoding="utf-8")
        self.assertIn("evidence_document_details(", code)
        self.assertIn("doc.superseded_by", code)
        self.assertIn("confirm_evidence_link=bool(required)", code)
        self.assertIn('"publication_status": "Published"', code)
        self.assertIn('"related_milestone_type": milestone', code)

    def test_api_has_post_confirmation_and_read_only_preview(self):
        code = API.read_text(encoding="utf-8")
        self.assertIn('def preview_bulk_completion(selected, reason=None):', code)
        self.assertIn('def complete_bulk_milestones(selected, evidence_document=None,', code)
        tree = ast.parse(code)
        functions = {f.name for f in tree.body if isinstance(f, ast.FunctionDef)}
        self.assertTrue({"preview_bulk_completion", "complete_bulk_milestones"}.issubset(functions))

    def test_grid_bulk_uses_multiple_codes_and_clears_selection_on_reload(self):
        code = GRID.read_text(encoding="utf-8")
        self.assertIn('state.designCodes.length>0', code)
        self.assertIn('state.selectedBulk.clear()', code)
        self.assertIn('bulkSignature', code)
        self.assertIn('Select All', code)
        self.assertIn('Complete Selected', code)
        self.assertIn('preview_bulk_completion', code)
        self.assertIn('complete_bulk_milestones', code)
        self.assertIn('search_bulk_evidence', code)


if __name__ == "__main__":
    unittest.main()
