"""Offline Release 1 costing math, metadata and workflow regression contracts.

Live Frappe Cloud tests are still necessary for permissions, locking, file
ownership, approval transitions and link integrity.
"""
import ast
from collections import defaultdict
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2] / "marina_custom_apps"
BASE = ROOT / "marina_design_management" / "doctype" / "design_cost_breakdown"
PY = BASE / "design_cost_breakdown.py"
API = ROOT / "design_management" / "cost_breakdown_api.py"
DOCTYPES = ROOT / "marina_design_management" / "doctype"


class FrappeStub:
    class PermissionError(Exception):
        pass

    def throw(self, message, *args, **kwargs):
        raise ValueError(message)


class Row(dict):
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value


class CostDocument:
    def __init__(self, lines, items, costing_method="Hybrid"):
        self.cost_components = lines
        self.price_qty_lines = items
        self.costing_method = costing_method
        self.exchange_rate_sar = 3.75

    def get(self, field):
        return getattr(self, field, None)


def extract(name, source, env, class_name=None):
    nodes = ast.parse(source.read_text()).body
    if class_name:
        node = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name)
        target = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    else:
        target = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    target.decorator_list = []
    namespace = dict(env)
    exec(compile(ast.Module(body=[target], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


class CostMathTests(unittest.TestCase):
    def setUp(self):
        fake = FrappeStub()
        number = extract("_number", PY, {"frappe": fake, "isfinite": __import__("math").isfinite})
        self.calculate = extract("_calculate", PY, {
            "frappe": fake,
            "_number": number,
            "_variant_map": lambda design: {
                row.production_key: row for row in design.production_items
            },
            "defaultdict": defaultdict,
            "flt": lambda n, precision=2: round(float(n or 0), precision),
        }, "DesignCostBreakdown")
        self.design = SimpleNamespace(production_items=[
            Row(production_key="red", item_code="SKU-RED", color_name="Red"),
            Row(production_key="blue", item_code="SKU-BLUE", color_name="Blue"),
        ])

    def test_common_and_variant_order_cost_allocations(self):
        items = [
            Row(variant_code="Red", production_key="red", proposed_qty=50,
                moq=25, supplier_quoted_price=18, negotiated_unit_price=16,
                planned_item_code=""),
            Row(variant_code="Blue", production_key="blue", proposed_qty=50,
                moq=25, supplier_quoted_price=20, negotiated_unit_price=18,
                planned_item_code=""),
        ]
        components = [
            Row(description="Main fabric", cost_category="Main Fabric",
                applies_to="All Variants", variant_code="", cost_basis="Per Piece",
                consumption=2, unit_rate=3.5, wastage_percent=0),
            Row(description="Red tooling", cost_category="Other Manufacturing Cost",
                applies_to="Specific Variant", variant_code="Red", cost_basis="Per Order",
                consumption=1, unit_rate=100, wastage_percent=0),
        ]
        doc = CostDocument(components, items)
        self.calculate(doc, self.design)
        self.assertEqual(doc.total_qty, 100)
        self.assertEqual(doc.total_quoted_value, 1900)
        self.assertEqual(doc.total_purchase_value, 1700)
        self.assertEqual(doc.savings_value, 200)
        self.assertEqual(doc.weighted_unit_price, 17)
        self.assertEqual(items[0].estimated_component_cost, 9)
        self.assertEqual(items[1].estimated_component_cost, 7)
        self.assertEqual(doc.estimated_component_value, 800)
        self.assertEqual(doc.estimated_sar_value, 6375)
        self.assertEqual(items[0].planned_item_code, "SKU-RED")

    def test_quotation_only_has_no_mandatory_components(self):
        doc = CostDocument([], [Row(variant_code="One", production_key="",
            planned_item_code="", proposed_qty=10, moq=0,
            supplier_quoted_price=15, negotiated_unit_price=12)], "Quotation Only")
        self.calculate(doc, SimpleNamespace(production_items=[]))
        self.assertEqual(doc.total_purchase_value, 120)
        self.assertEqual(doc.estimated_component_value, 0)

    def test_duplicate_variant_rejected(self):
        doc = CostDocument([], [Row(variant_code="RED", proposed_qty=10, moq=0,
            supplier_quoted_price=12, negotiated_unit_price=11),
            Row(variant_code="red", proposed_qty=5, moq=0,
            supplier_quoted_price=12, negotiated_unit_price=11)])
        with self.assertRaisesRegex(ValueError, "Duplicate Color"):
            self.calculate(doc, SimpleNamespace(production_items=[]))

    def test_claimed_planned_code_without_reference_rejected(self):
        doc = CostDocument([], [Row(variant_code="Red", planned_item_code="OTHER",
            proposed_qty=2, moq=0, supplier_quoted_price=12, negotiated_unit_price=11)])
        with self.assertRaisesRegex(ValueError, "unlinked variant"):
            self.calculate(doc, SimpleNamespace(production_items=[]))

    def test_variant_production_reference_must_match_color(self):
        doc = CostDocument([], [Row(variant_code="Blue", production_key="red",
            proposed_qty=2, moq=0, supplier_quoted_price=12, negotiated_unit_price=11)])
        with self.assertRaisesRegex(ValueError, "differs from costing variant"):
            self.calculate(doc, self.design)


class MetadataAndSecurityContracts(unittest.TestCase):
    def test_parent_and_child_structure(self):
        names = {
            "design_cost_breakdown": ("Design Cost Breakdown", False),
            "design_cost_component": ("Design Cost Component", True),
            "design_cost_price_qty": ("Design Cost Price Qty", True),
        }
        for slug, (label, child) in names.items():
            doc = json.loads((DOCTYPES/slug/(slug+".json")).read_text())
            self.assertEqual(doc["name"], label)
            self.assertEqual(bool(doc["istable"]), child)
            self.assertEqual(doc["module"], "Marina Design Management")
            fields = {field["fieldname"]: field for field in doc["fields"]}
            if not child:
                self.assertEqual(fields["cost_components"]["options"], "Design Cost Component")
                self.assertEqual(fields["price_qty_lines"]["options"], "Design Cost Price Qty")
                self.assertIn("Approved", fields["status"]["options"])
                self.assertIn("Quotation Only", fields["costing_method"]["options"])
                self.assertEqual(doc["track_changes"], 1)

    def test_no_milestone_or_purchase_document_mutations(self):
        text = PY.read_text() + "\n" + API.read_text()
        self.assertNotIn('frappe.get_doc({"doctype": "Purchase Order"', text)
        self.assertNotIn('frappe.db.set_value("Design Production Item"', text)
        self.assertNotIn('frappe.db.set_value("Design Production Size"', text)
        self.assertNotIn('frappe.db.set_value("Design Milestone Execution"', text)
        self.assertIn("Approved, Superseded and Cancelled commercial records are immutable", text)
        self.assertIn('SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE', text)
        self.assertIn('frappe.db.set_value("Design Cost Breakdown"', text)
        self.assertIn('current[0].name', text)

    def test_action_and_permission_wiring(self):
        hooks = (ROOT/"hooks.py").read_text()
        perms = (ROOT/"security"/"permissions.py").read_text()
        roles = (ROOT/"security"/"role_access.py").read_text()
        seeds = (ROOT/"setup"/"module_role_defaults.py").read_text()
        self.assertIn('"Design Cost Breakdown": "marina_design_management.security.permissions.cost_breakdown_query"', hooks)
        self.assertIn("def cost_breakdown_permission", perms)
        self.assertIn("Approve Design Cost Breakdown", roles)
        self.assertIn("sync_cost_breakdown_permissions", seeds)

    def test_revision_api_requires_existing_approval(self):
        src = API.read_text()
        self.assertIn('source.status not in ("Approved", "Superseded", "Cancelled")', src)
        self.assertIn('"quotation_attachment": None', src)
        self.assertIn('doc.status != "Pending Approval"', src)
        self.assertIn('doc.flags.cost_transition = "approve"', src)
        self.assertIn('doc.flags.cost_transition = "return"', src)
        self.assertIn('doc.flags.cost_transition = "submit"', src)
        self.assertIn('doc.flags.cost_transition = "cancel"', src)
        self.assertIn('doc.status = "Cancelled"', src)
        self.assertIn('reason = (reason or "").strip()', src)
        self.assertIn('doc.save(ignore_permissions=True)', src)
        self.assertIn('active_approval_remaining', src)



if __name__ == "__main__":
    unittest.main()
