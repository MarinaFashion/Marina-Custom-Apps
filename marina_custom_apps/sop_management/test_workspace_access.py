import json
import unittest
from pathlib import Path


class UmbrellaWorkspaceAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace_path = (
            Path(__file__).resolve().parent
            / "workspace"
            / "marina_custom_apps"
            / "marina_custom_apps.json"
        )
        cls.workspace = json.loads(workspace_path.read_text(encoding="utf-8"))

    def test_umbrella_is_public_root_workspace(self):
        self.assertEqual(self.workspace.get("public"), 1)
        self.assertFalse(self.workspace.get("parent_page"))

    def test_umbrella_is_not_restricted_by_business_module(self):
        self.assertFalse(self.workspace.get("module"))


if __name__ == "__main__":
    unittest.main()
