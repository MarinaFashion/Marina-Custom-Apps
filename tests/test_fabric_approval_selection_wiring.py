"""Fabric Approval is an explicit pre-planning choice, not a default or live toggle."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
CODE = ROOT / "marina_design_management/doctype/design_code"
SERVICE = ROOT / "design_management/clean_milestones/service.py"
BULK = ROOT / "design_management/clean_milestones/bulk_create.py"


class FabricApprovalSelectionTests(unittest.TestCase):
    def test_select_requires_explicit_choice(self):
        schema = json.loads((CODE / "design_code.json").read_text())
        field = next(f for f in schema["fields"]
                     if f["fieldname"] == "fabric_approval_required")
        self.assertEqual(field["label"], "Fabric Approval")
        self.assertEqual(field["fieldtype"], "Select")
        self.assertEqual(field["options"].splitlines(), ["", "Required", "Not Required"])
        self.assertEqual(field.get("default"), "")
        # Existing designs must remain editable; planning is the mandatory gate.
        self.assertFalse(field.get("reqd"))

    def test_single_and_bulk_creation_are_gated(self):
        service = SERVICE.read_text()
        bulk = BULK.read_text()
        ast.parse(service)
        ast.parse(bulk)
        self.assertIn('design.fabric_approval_required not in ("Required", "Not Required")', service)
        self.assertIn('design.get("fabric_approval_required") not in ("Required", "Not Required")', bulk)
        self.assertLess(service.index('design.fabric_approval_required not in'),
                        service.index('snapshots = _snapshots(milestone_types)'))

    def test_choice_is_locked_after_plan_creation(self):
        source = (CODE / "design_code.py").read_text()
        ast.parse(source)
        self.assertIn('before.get("fabric_approval_required")', source)
        self.assertIn('"Fabric Approval cannot change after milestones are created"', source)


if __name__ == "__main__":
    unittest.main()
