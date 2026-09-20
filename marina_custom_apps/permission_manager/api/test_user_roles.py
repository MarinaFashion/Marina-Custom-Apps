import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeUser:
    def __init__(self, name="manager@example.com", roles=(), profile=""):
        self.name = name
        self.enabled = 1
        self.user_type = "System User"
        self.full_name = "Manager"
        self.role_profile_name = profile
        self.roles = [types.SimpleNamespace(role=role) for role in roles]
        self.saves = 0

    def append(self, field, values):
        self.roles.append(types.SimpleNamespace(**values))

    def save(self, ignore_permissions=False):
        if not ignore_permissions:
            raise AssertionError("Expected User validation save")
        self.saves += 1


class UserRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe = types.ModuleType("frappe")
        frappe.whitelist = lambda: lambda function: function
        frappe.only_for = lambda role: None
        frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))
        frappe.bold = str
        frappe._ = lambda message: message
        frappe.parse_json = json.loads
        frappe.session = types.SimpleNamespace(user="manager@example.com")
        utils = types.ModuleType("frappe.utils")
        utils.cint = int
        user_module = types.ModuleType("frappe.core.doctype.user.user")
        user_module.get_all_roles = lambda: ["System Manager", "Stock Manager", "Sales User"]
        cls.patcher = patch.dict(sys.modules, {
            "frappe": frappe, "frappe.utils": utils,
            "frappe.core": types.ModuleType("frappe.core"),
            "frappe.core.doctype": types.ModuleType("frappe.core.doctype"),
            "frappe.core.doctype.user": types.ModuleType("frappe.core.doctype.user"),
            "frappe.core.doctype.user.user": user_module,
        })
        cls.patcher.start()
        spec = importlib.util.spec_from_file_location("role_api_under_test", Path(__file__).with_name("user_roles.py"))
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)
        cls.frappe = frappe

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()

    def test_role_profile_is_not_detached_by_bulk_edit(self):
        doc = FakeUser(profile="Stock Team", roles=["Stock Manager"])
        self.frappe.get_doc = lambda *args: doc
        with self.assertRaisesRegex(ValueError, "Role Profile"):
            self.api.save_role_users("Sales User", [{"user": doc.name, "assigned": 1, "expected": 0}])
        self.assertEqual(doc.saves, 0)
        self.assertEqual(doc.role_profile_name, "Stock Team")

    def test_user_save_preserves_unrelated_role_and_uses_user_lifecycle(self):
        doc = FakeUser(roles=["System Manager", "Stock Manager", "Legacy Role"])
        self.frappe.get_doc = lambda *args: doc
        result = self.api.save_user_roles(doc.name, ["System Manager", "Sales User"], ["System Manager", "Stock Manager"])
        self.assertEqual(result, {"updated_users": 1})
        self.assertEqual({r.role for r in doc.roles}, {"System Manager", "Sales User", "Legacy Role"})
        self.assertEqual(doc.saves, 1)

    def test_cannot_remove_own_manager_role(self):
        doc = FakeUser(roles=["System Manager", "Stock Manager"])
        self.frappe.get_doc = lambda *args: doc
        with self.assertRaisesRegex(ValueError, "your own System Manager"):
            self.api.save_user_roles(doc.name, ["Stock Manager"], ["System Manager", "Stock Manager"])
        self.assertEqual(doc.saves, 0)

    def test_stale_assignment_is_rejected_before_write(self):
        doc = FakeUser(name="other@example.com", roles=["Stock Manager"])
        self.frappe.get_doc = lambda *args: doc
        with self.assertRaisesRegex(ValueError, "changed since loading"):
            self.api.save_role_users("Stock Manager", [{"user": doc.name, "assigned": 0, "expected": 0}])
        self.assertEqual(doc.saves, 0)

    def test_page_and_dashboard_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        page = json.loads((root / "page/marina_user_role_manager/marina_user_role_manager.json").read_text())
        workspace = json.loads((root / "workspace/permission_manager_dashboard/permission_manager_dashboard.json").read_text())
        self.assertEqual(page["roles"], [{"role": "System Manager"}])
        self.assertIn("marina-user-role-manager", [row.get("link_to") for row in workspace["shortcuts"]])
        self.assertIn("User Role Manager", [row["data"].get("shortcut_name") for row in json.loads(workspace["content"]) if row["type"] == "shortcut"])


if __name__ == "__main__":
    unittest.main()
