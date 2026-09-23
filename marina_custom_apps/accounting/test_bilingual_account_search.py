import ast
import json
import unittest
from pathlib import Path


class BilingualAccountSearchMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_root = Path(__file__).resolve().parents[1]

    def test_account_arabic_name_is_created_without_renaming_accounts(self):
        source = (self.app_root / "install.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn('"Account": [', source)
        self.assertIn('"fieldname": "custom_account_name_arabic"', source)
        self.assertNotIn("rename_doc", source)
        self.assertIn("_ensure_bilingual_account_search_default()", source)
        self.assertIn("if current is None:", source)
        self.assertTrue(any(isinstance(node, ast.FunctionDef) for node in tree.body))

    def test_settings_default_on_and_contains_kill_switch(self):
        path = (
            self.app_root
            / "marina_custom_apps/doctype/marina_accounting_settings/marina_accounting_settings.json"
        )
        definition = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(definition["module"], "Marina Custom Apps")
        fields = {row["fieldname"]: row for row in definition["fields"]}
        toggle = fields["enable_bilingual_account_search"]
        self.assertEqual(toggle["fieldtype"], "Check")
        self.assertEqual(toggle["default"], "1")

    def test_settings_doctype_is_inside_its_registered_module_directory(self):
        modules = (self.app_root / "modules.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("Marina Custom Apps", modules)
        expected = (
            self.app_root
            / "marina_custom_apps/doctype/marina_accounting_settings/marina_accounting_settings.json"
        )
        obsolete = (
            self.app_root
            / "accounting/doctype/marina_accounting_settings/marina_accounting_settings.json"
        )
        self.assertTrue(expected.is_file())
        self.assertFalse(obsolete.exists())

    def test_journal_entry_uses_reversible_server_query(self):
        hooks = (self.app_root / "hooks.py").read_text(encoding="utf-8")
        query = (
            self.app_root / "accounting/bilingual_account_search.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"Journal Entry": "public/js/bilingual_account_search.js"', hooks)
        self.assertIn("if not _is_enabled() or not _has_arabic_field():", query)
        self.assertIn("_standard_account_query", query)


if __name__ == "__main__":
    unittest.main()
