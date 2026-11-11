"""Prevent Select option drift from the server-authoritative action catalog."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
FILES = [
    ROOT / "marina_design_management/doctype/design_user_action_permission/design_user_action_permission.json",
    ROOT / "marina_design_management/doctype/design_module_action_permission/design_module_action_permission.json",
]
USER_ACTIONS = ROOT / "design_management/security/user_permissions.py"
MODULE_ACTIONS = ROOT / "design_management/security/role_access.py"


def actions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ACTIONS" for t in node.targets)):
            call = node.value
            if isinstance(call, ast.Call) and call.args:
                return set(ast.literal_eval(call.args[0]))
    raise AssertionError("Missing ACTIONS catalog: " + str(path))


class ActionCatalogSyncTests(unittest.TestCase):
    def test_server_catalogs_agree(self):
        self.assertEqual(actions(USER_ACTIONS), actions(MODULE_ACTIONS))

    def test_child_select_options_cover_every_authorized_action(self):
        expected = actions(USER_ACTIONS)
        for path in FILES:
            with self.subTest(path=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                field = next(f for f in doc["fields"] if f["fieldname"] == "action_key")
                options = field["options"].splitlines()
                self.assertEqual(len(options), len(set(options)))
                self.assertEqual(set(options), expected)


if __name__ == "__main__":
    unittest.main()
