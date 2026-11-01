"""Static regression: root workspaces retain their own roles and direct navigation."""
import ast
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WS = [
    "marina_custom_apps/cycle_count/workspace/cycle_count/cycle_count.json",
    "marina_custom_apps/dc_dispatch/workspace/dc_dispatch/dc_dispatch.json",
    "marina_custom_apps/marina_calendar/workspace/marina_calendar/marina_calendar.json",
    "marina_custom_apps/pos_reconciliation/workspace/pos_reconciliation/pos_reconciliation.json",
    "marina_custom_apps/sales_forecasting/workspace/sales_forecasting/sales_forecasting.json",
    "marina_custom_apps/sop_management/workspace/sop_management/sop_management.json",
    "marina_custom_apps/stock_auto_allocation/workspace/stock_auto_allocation/stock_auto_allocation.json",
    "marina_custom_apps/stock_transfer_audit/workspace/stock_transfer_audit/stock_transfer_audit.json",
]

class IndependentWorkspaceTests(unittest.TestCase):
    def test_root_json_config(self):
        for name in WS:
            with self.subTest(file=name):
                data = json.loads((ROOT / name).read_text())
                self.assertEqual(data["parent_page"], "")
                self.assertEqual(data["public"], 1)
                self.assertEqual(data["is_hidden"], 0)
        hub = json.loads((ROOT / "marina_custom_apps/sop_management/workspace/marina_custom_apps/marina_custom_apps.json").read_text())
        self.assertEqual(hub["is_hidden"], 1)

    def test_migration_is_non_destructive_and_after_sync(self):
        source = (ROOT / "marina_custom_apps/workspace_layout.py").read_text()
        self.assertIn('update_modified=False', source)
        self.assertNotIn('frappe.db.delete(', source)
        self.assertNotIn('.save(', source)
        self.assertNotIn('frappe.db.commit(', source)
        hooks = (ROOT / "marina_custom_apps/sales_forecasting/install.py").read_text()
        self.assertIn('ensure_independent_workspaces()', hooks)
        self.assertIn('    design_after_migrate()\\n    from marina_custom_apps.workspace_layout', hooks)
        ast.parse(source)
        ast.parse(hooks)

if __name__ == "__main__":
    unittest.main()
