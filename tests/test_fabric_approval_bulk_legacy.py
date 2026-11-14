"""Guard Fabric Approval visibility and controlled bulk changes on legacy designs."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
BASE = ROOT / "marina_design_management/doctype/design_code"
BULK = ROOT / "design_management/clean_milestones/bulk_fabric_approval.py"


class FabricApprovalLegacyTests(unittest.TestCase):
    def test_visible_on_saved_design_and_list(self):
        schema = json.loads((BASE / "design_code.json").read_text())
        field = next(f for f in schema["fields"]
                     if f["fieldname"] == "fabric_approval_required")
        self.assertEqual(field["fieldtype"], "Select")
        self.assertEqual(field["options"].splitlines(), ["", "Required", "Not Required"])
        self.assertEqual(field.get("in_list_view"), 1)
        self.assertEqual(field.get("in_standard_filter"), 1)
        js = (BASE / "design_code.js").read_text()
        self.assertIn('set_df_property("fabric_approval_required","hidden",0)', js)
        self.assertIn('set_df_property("fabric_approval_required","read_only",info?.has_plan?1:0', js)

    def test_historical_completed_backfill_is_classification_only(self):
        code = BULK.read_text()
        ast.parse(code)
        self.assertIn('fabric[0].plan_state == "Completed"', code)
        self.assertIn('previous == "" and approval == "Not Required"', code)
        self.assertIn('"historical" if historical else "ready"', code)
        self.assertIn('if row["status"] == "historical":', code)
        self.assertIn('elif row["has_plan"]:', code)
        self.assertIn("switch_existing_plan(design, approval, note)", code)
        self.assertIn("completed Fabric Sourcing", code)

    def test_safe_batch_actions(self):
        js = (BASE / "design_code_list.js").read_text()
        self.assertIn('add_action_item(__("Set Fabric Approval")', js)
        self.assertIn("preview_bulk_fabric_approval", js)
        self.assertIn("set_bulk_fabric_approval", js)
        self.assertIn('preview.blocked || !preview.ready', js)
        code = BULK.read_text()
        ast.parse(code)
        self.assertIn("MAX_BATCH = 20", code)
        self.assertIn("service._lock_design(name)", code)
        self.assertIn('service._authorize(frappe.session.user, "Assign Milestones", design)', code)
        self.assertIn("switch_existing_plan(design, approval, note)", code)
        self.assertIn('if any(row["status"] == "blocked" for row in rows)', code)
        self.assertIn('"reference_doctype": "Design Code"', code)
        self.assertNotIn("frappe.db.commit(", code)


if __name__ == "__main__":
    unittest.main()
