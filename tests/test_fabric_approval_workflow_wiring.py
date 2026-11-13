"""Regression protection for conditional fabric review and controlled changes."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
SOURCE = ROOT / "design_management/clean_milestones"
DESIGN = ROOT / "marina_design_management/doctype/design_code"


class FabricApprovalWorkflowTests(unittest.TestCase):
    def test_optional_review_steps(self):
        mod = (SOURCE / "fabric_approval.py").read_text()
        ast.parse(mod)
        self.assertIn('MILESTONE = "Fabric / Material Sourcing"', mod)
        self.assertIn('if approval == "Not Required":', mod)
        self.assertIn('result = [first, last]', mod)
        self.assertIn('step("Ready", "Manual", role, "Designer")', mod)
        self.assertIn('step("Rework", "Manual", "Designer", role)', mod)
        self.assertIn('"Designer" if approval == "Required" else role', mod)
        self.assertIn('snapshot["fabric_base_steps"] = base', mod)

    def test_creation_freezes_choice(self):
        service = (SOURCE / "service.py").read_text()
        ast.parse(service)
        self.assertIn('configure_snapshot(cfg, design.fabric_approval_required)', service)
        self.assertLess(
            service.index('configure_snapshot(cfg, design.fabric_approval_required)'),
            service.index('initial_plan_rows = ['),
        )

    def test_change_cannot_complete_or_skip_review(self):
        mod = (SOURCE / "fabric_approval.py").read_text()
        self.assertIn('plan.plan_state == "Completed"', mod)
        self.assertIn('execution.status == "Completed"', mod)
        self.assertIn('if previous in ("Ready", "Rework")', mod)
        self.assertIn('"status": "In Progress"', mod)
        self.assertIn('"workflow_snapshot_json"', mod)
        self.assertIn('"Fabric Approval Changed"', mod)

    def test_change_permission_reason_and_audit(self):
        api = (SOURCE / "api.py").read_text()
        ast.parse(api)
        self.assertIn('def change_fabric_approval(', api)
        self.assertIn('service._lock_design(design_code)', api)
        self.assertIn('design.check_permission("write")', api)
        self.assertIn('service._authorize(frappe.session.user, "Assign Milestones", design)', api)
        self.assertIn('len(reason.strip()) < 5', api)
        self.assertIn('comment_type": "Info"', api)
        self.assertIn('previous_approval', api)

    def test_controlled_form_action(self):
        js = (DESIGN / "design_code.js").read_text()
        self.assertIn('marina_design_button(frm,"Change Fabric Approval"', js)
        self.assertIn('"fabric_approval_required","read_only",info?.has_plan?1:0', js)
        self.assertIn("api.change_fabric_approval", js)
        self.assertIn('fieldname:"reason"', js)


if __name__ == "__main__":
    unittest.main()
