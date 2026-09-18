import ast
import json
import unittest
from pathlib import Path


class OperationalNamingSeriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_root = Path(__file__).resolve().parent
        cls.expected = {
            "cycle_count/doctype/cycle_count_plan/cycle_count_plan.json": "CCP-.YYYY.-.#####",
            "cycle_count/doctype/store_cycle_count/store_cycle_count.json": "SCC-.YYYY.-.#####",
            "dc_dispatch/doctype/dc_dispatch_run/dc_dispatch_run.json": "DCD-.YYYY.-.#####",
            "sales_forecasting/doctype/sales_forecast_run/sales_forecast_run.json": "SFR-.YYYY.-.#####",
            "sop_management/doctype/sop_document/sop_document.json": "SOP-.#####",
            "sop_management/doctype/sop_version/sop_version.json": "SOP-V-.#####",
            "stock_auto_allocation/doctype/stock_allocation_run/stock_allocation_run.json": "SAR-.YYYY.-.#####",
            "stock_auto_allocation/doctype/transfer_shipment_batch/transfer_shipment_batch.json": "TSB-.YYYY.-.#####",
            "stock_transfer_audit/doctype/stock_transfer_audit_run/stock_transfer_audit_run.json": "STA-RUN-.#####",
            "stock_transfer_audit/doctype/stock_transfer_audit_record/stock_transfer_audit_record.json": "STA-REC-.#####",
        }

    def test_operational_doctypes_use_required_naming_series(self):
        for relative_path, series in self.expected.items():
            with self.subTest(relative_path=relative_path):
                definition = json.loads((self.app_root / relative_path).read_text(encoding="utf-8"))
                self.assertEqual(definition.get("autoname"), "naming_series:")
                fields = {row.get("fieldname"): row for row in definition.get("fields", [])}
                naming_field = fields["naming_series"]
                self.assertEqual(naming_field.get("default"), series)
                self.assertIn(series, naming_field.get("options", "").splitlines())
                self.assertEqual(naming_field.get("reqd"), 1)

    def test_one_time_reset_patch_covers_every_prefix(self):
        patch_path = self.app_root / "patches" / "v0_47_20" / "reset_operational_naming_series.py"
        tree = ast.parse(patch_path.read_text(encoding="utf-8"))
        source = patch_path.read_text(encoding="utf-8")
        for series in self.expected.values():
            static_prefix = series.split(".", 1)[0]
            with self.subTest(series=series):
                self.assertIn(static_prefix, source)
        self.assertTrue(any(isinstance(node, ast.FunctionDef) and node.name == "execute" for node in tree.body))

    def test_patch_file_declares_both_frappe_patch_phases(self):
        patches = (self.app_root / "patches.txt").read_text(encoding="utf-8")
        self.assertIn("[pre_model_sync]", patches)
        self.assertIn("[post_model_sync]", patches)
        self.assertLess(patches.index("[pre_model_sync]"), patches.index("[post_model_sync]"))


if __name__ == "__main__":
    unittest.main()
