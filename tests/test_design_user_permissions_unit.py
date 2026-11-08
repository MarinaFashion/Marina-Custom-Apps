"""Pure-Python contract tests: no Frappe site or database is required."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class Row(dict):
    def __getattr__(self, name):
        return self[name]


class FakeDB:
    def __init__(self):
        self.active = True
        self.profile = True

    def exists(self, doctype, name):
        if doctype == "DocType":
            return True
        if doctype == "Design User Permission":
            return self.profile
        return False

    def table_exists(self, doctype):
        return True

    def get_value(self, doctype, name, field):
        if doctype == "User":
            return self.active
        raise AssertionError((doctype, name, field))


class PermissionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = sys.modules.get("frappe")
        cls.frappe = types.ModuleType("frappe")
        cls.frappe.db = FakeDB()
        cls.frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)
        cls.frappe.session = types.SimpleNamespace(user="catherine@example.test")
        cls.frappe.local = types.SimpleNamespace()
        cls.frappe.get_doc = lambda doctype, user: cls.profile
        sys.modules["frappe"] = cls.frappe
        path = (Path(__file__).resolve().parents[1] /
                "marina_custom_apps/design_management/security/user_permissions.py")
        spec = importlib.util.spec_from_file_location("_marina_policy_test", path)
        cls.policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.policy)

    @classmethod
    def tearDownClass(cls):
        if cls.original is None:
            sys.modules.pop("frappe", None)
        else:
            sys.modules["frappe"] = cls.original

    def setUp(self):
        self.frappe.local = types.SimpleNamespace()
        self.frappe.db.profile = True
        self.frappe.db.active = True
        self.profile = types.SimpleNamespace(
            enabled=1,
            document_permissions=[Row(
                resource_doctype="Design Code", read=1,
                create=1, write=0, delete=0,
            )],
            action_permissions=[
                Row(action_key="Assign Milestones", access="Allowed"),
                Row(action_key="Advance Milestone Step", access="Custody Only"),
                Row(action_key="Send Discussion Message", access="Not Allowed"),
            ],
        )
        self.__class__.profile = self.profile

    def test_explicit_document_allow_and_deny(self):
        self.assertTrue(self.policy.document_allowed("Design Code", "read"))
        self.assertFalse(self.policy.document_allowed("Design Code", "write"))
        self.assertFalse(self.policy.document_allowed("Mood Board", "read"))

    def test_action_allow_and_default_deny(self):
        self.assertTrue(self.policy.action_allowed("Assign Milestones"))
        self.assertFalse(self.policy.action_allowed("Send Discussion Message"))
        self.assertFalse(self.policy.action_allowed("Delete Design Code"))

    def test_custody_requires_matching_current_custodian(self):
        action = "Advance Milestone Step"
        self.assertTrue(self.policy.action_allowed(action, custodian="catherine@example.test"))
        self.assertFalse(self.policy.action_allowed(action, custodian="selly@example.test"))
        self.assertFalse(self.policy.action_allowed(action))

    def test_unconfigured_users_unchanged(self):
        self.frappe.db.profile = False
        self.assertIsNone(self.policy.document_allowed("Design Code", "write"))
        self.assertIsNone(self.policy.action_allowed("Assign Milestones"))

    def test_disabled_user_policy_is_inactive(self):
        self.profile.enabled = 0
        self.assertIsNone(self.policy.document_allowed("Design Code", "read"))
        self.assertIsNone(self.policy.action_allowed("Assign Milestones"))


if __name__ == "__main__":
    unittest.main()
