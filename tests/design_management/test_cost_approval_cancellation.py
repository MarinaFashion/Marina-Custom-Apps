"""Unit/contract tests for revoking a current commercial approval.

A cancellation must preserve approved values, have an authorized reviewer and
a durable reason, and never automatically resurrect a superseded quotation.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2] / "marina_custom_apps"
CODE = (ROOT / "marina_design_management" / "doctype" /
        "design_cost_breakdown" / "design_cost_breakdown.py")
SCHEMA = CODE.with_suffix(".json")
API = ROOT / "design_management" / "cost_breakdown_api.py"
CLIENT = CODE.with_suffix(".js")
LIST = CODE.parent / "design_cost_breakdown_list.js"


class FakeFrappe:
    class PermissionError(Exception):
        pass

    def throw(self, text, *_args, **_kw):
        raise ValueError(text)


class Row:
    def __init__(self, **values):
        self.values = values

    def as_dict(self):
        return dict(self.values)


class CostDocument:
    FIELDS = [
        ("design_code", "Design Code", "Link"),
        ("status", "Status", "Select"),
        ("approved_by", "Approved By", "Link"),
        ("approved_on", "Approved On", "Datetime"),
        ("prepared_by", "Prepared By", "Link"),
        ("submitted_by", "Submitted By", "Link"),
        ("total_purchase_value", "Total Purchase Value", "Currency"),
        ("price_qty_lines", "Price and Quantity Lines", "Table"),
        ("cost_components", "Cost Components", "Table"),
        ("cancelled_by", "Cancelled By", "Link"),
        ("cancelled_on", "Cancelled On", "Datetime"),
        ("cancellation_reason", "Cancellation Reason", "Small Text"),
    ]

    def __init__(self, *, cancelled=False):
        self.data = {
            "design_code": "S27-R-016T",
            "status": "Cancelled" if cancelled else "Approved",
            "approved_by": "original_buyer",
            "approved_on": "2026-11-01 12:00:00",
            "prepared_by": "merchant",
            "submitted_by": "merchant",
            "total_purchase_value": 1700,
            "price_qty_lines": [Row(variant_code="Red", proposed_qty=50,
                                   negotiated_unit_price=16)],
            "cost_components": [Row(cost_category="Fabric", unit_rate=7)],
            "cancelled_by": "buyer" if cancelled else None,
            "cancelled_on": "2026-11-01 19:30:00" if cancelled else None,
            "cancellation_reason": ("Factory amended quotation unexpectedly"
                                    if cancelled else None),
        }
        self.meta = SimpleNamespace(fields=[
            SimpleNamespace(fieldname=a, label=b, fieldtype=c)
            for a, b, c in self.FIELDS
        ])

    def __getattr__(self, key):
        if key in self.data:
            return self.data[key]
        raise AttributeError(key)

    def get(self, key):
        return self.data.get(key)


def load_cancel_validator(buyer=True):
    tree = ast.parse(CODE.read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef)
               and x.name == "DesignCostBreakdown")
    node = next(x for x in cls.body if isinstance(x, ast.FunctionDef)
                and x.name == "_validate_approval_cancellation")
    namespace = {"frappe": FakeFrappe(), "_buyer": lambda _: buyer}
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 str(CODE), "exec"), namespace)
    return namespace["_validate_approval_cancellation"]


class CancelApprovalTests(unittest.TestCase):
    def test_revoke_only_updates_status_and_cancel_metadata(self):
        before = CostDocument()
        after = CostDocument(cancelled=True)
        load_cancel_validator()(after, before, "buyer")
        self.assertEqual(after.total_purchase_value, before.total_purchase_value)
        self.assertEqual(after.approved_by, before.approved_by)

    def test_cancel_denied_if_not_buyer(self):
        with self.assertRaisesRegex(ValueError, "Buying Manager"):
            load_cancel_validator(buyer=False)(
                CostDocument(cancelled=True), CostDocument(), "buyer"
            )

    def test_original_preparer_cannot_cancel(self):
        doc = CostDocument(cancelled=True)
        doc.data["cancelled_by"] = "merchant"
        with self.assertRaisesRegex(ValueError, "preparer"):
            load_cancel_validator()(doc, CostDocument(), "merchant")

    def test_cancellation_reason_required(self):
        doc = CostDocument(cancelled=True)
        doc.data["cancellation_reason"] = "short"
        with self.assertRaisesRegex(ValueError, "10–500"):
            load_cancel_validator()(doc, CostDocument(), "buyer")

    def test_cannot_edit_approved_total_while_cancelling(self):
        doc = CostDocument(cancelled=True)
        doc.data["total_purchase_value"] = 1
        with self.assertRaisesRegex(ValueError, "Total Purchase Value"):
            load_cancel_validator()(doc, CostDocument(), "buyer")

    def test_cannot_edit_price_qty_child_while_cancelling(self):
        doc = CostDocument(cancelled=True)
        doc.price_qty_lines[0].values["negotiated_unit_price"] = 9
        with self.assertRaisesRegex(ValueError, "price rows"):
            load_cancel_validator()(doc, CostDocument(), "buyer")

    def test_cannot_edit_original_approval_actor(self):
        doc = CostDocument(cancelled=True)
        doc.data["approved_by"] = "replacement"
        with self.assertRaisesRegex(ValueError, "Approved By"):
            load_cancel_validator()(doc, CostDocument(), "buyer")

    def test_cancel_button_and_terminal_schema(self):
        parent = json.loads(SCHEMA.read_text())
        fields = {x["fieldname"]: x for x in parent["fields"]}
        self.assertIn("Cancelled", fields["status"]["options"].split("\n"))
        for name in ("cancelled_by", "cancelled_on", "cancellation_reason"):
            self.assertEqual(fields[name]["read_only"], 1)
        script = CLIENT.read_text()
        self.assertIn('if(actions.can_cancel)', script)
        self.assertIn('Cancel Approval', script)
        self.assertIn('cancel_approved_cost_breakdown', script)
        self.assertIn('"Superseded","Cancelled"', script)
        self.assertIn('"Cancelled"', LIST.read_text())

    def test_server_locks_design_and_never_restores_old_approval(self):
        s = API.read_text()
        a = s.index("def cancel_approved_cost_breakdown(")
        b = s.index("@frappe.whitelist", a)
        body = s[a:b]
        self.assertIn('_approval_access(design, doc)', body)
        self.assertIn("FOR UPDATE", body)
        self.assertIn("doc.reload()", body)
        self.assertIn('doc.status != "Approved"', body)
        self.assertIn('doc.status = "Cancelled"', body)
        self.assertIn('doc.flags.cost_transition = "cancel"', body)
        # The guard legitimately queries status=Approved to reject duplicates.
        # Cancellation must never change any historical version back to it.
        self.assertNotIn('doc.status = "Approved"', body)
        self.assertNotIn('frappe.db.set_value("Design Cost Breakdown"', body)
        self.assertNotIn("frappe.db.commit", body)
        self.assertIn('"Cancelled"', s[s.index("def create_cost_revision("):])
        self.assertIn('"can_cancel"', s[s.index("def cost_actions("):])


if __name__ == "__main__":
    unittest.main()
