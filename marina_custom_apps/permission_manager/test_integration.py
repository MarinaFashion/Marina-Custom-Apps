import json
import unittest
from pathlib import Path


class PermissionManagerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_root = Path(__file__).resolve().parents[1]
        cls.module_root = Path(__file__).resolve().parent
        workspace_path = (
            cls.module_root
            / "workspace"
            / "permission_manager_dashboard"
            / "permission_manager_dashboard.json"
        )
        cls.workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
        umbrella_path = (
            cls.app_root
            / "sop_management"
            / "workspace"
            / "marina_custom_apps"
            / "marina_custom_apps.json"
        )
        cls.umbrella = json.loads(umbrella_path.read_text(encoding="utf-8"))

    def test_module_is_declared_by_marina_custom_apps(self):
        modules = (self.app_root / "modules.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("Permission Manager", modules)

    def test_workspace_is_a_system_manager_child(self):
        self.assertEqual(self.workspace.get("module"), "Permission Manager")
        self.assertEqual(self.workspace.get("parent_page"), "Marina Custom Apps")
        self.assertEqual(
            {row.get("role") for row in self.workspace.get("roles", [])},
            {"System Manager"},
        )

    def test_standalone_python_namespace_is_removed(self):
        stale = []
        for path in self.module_root.rglob("*"):
            if path == Path(__file__).resolve():
                continue
            if path.is_file() and path.suffix in {".py", ".js", ".json"}:
                if "marina_permission_manager" in path.read_text(encoding="utf-8"):
                    stale.append(str(path.relative_to(self.module_root)))
        self.assertEqual(stale, [])

    def test_umbrella_shortcut_uses_role_filtered_page(self):
        shortcut = next(
            row
            for row in self.umbrella.get("shortcuts", [])
            if row.get("label") == "Permission Manager"
        )
        self.assertEqual(shortcut.get("type"), "Page")
        self.assertEqual(shortcut.get("link_to"), "marina-permission-manager")


if __name__ == "__main__":
    unittest.main()
