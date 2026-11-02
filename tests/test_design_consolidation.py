"""Static architecture contracts for Design Management consolidation."""
import ast
import json
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
APP=ROOT/"marina_custom_apps"
DESIGN=APP/"design_management"
MODULE=APP/"marina_design_management"

class ConsolidationContracts(unittest.TestCase):
    def test_all_packages_and_doctypes_present(self):
        self.assertTrue((DESIGN/"setup"/"install.py").exists())
        self.assertTrue((MODULE/"__init__.py").exists())
        for dt in ["Design Code","Mood Board","Design Document","Design Cost Breakdown","Design Milestone Execution","Marina Discussion Message"]:
            name=dt.lower().replace(" ","_")
            path=MODULE/"doctype"/name/(name+".json")
            self.assertTrue(path.exists(), str(path))
            definition=json.loads(path.read_text())
            self.assertEqual(definition["name"],dt)
            self.assertEqual(definition["module"],"Marina Design Management")

    def test_integrated_hooks_and_bootstrap(self):
        hooks=(APP/"hooks.py").read_text()
        for value in ("cost_breakdown_permission", "discussion_retention.expire_large_attachments",
                      "app_include_js", "Marina Discussion Message", "discussion_activity"):
            if value=="discussion_activity":
                continue
            self.assertIn(value,hooks)
        self.assertIn("Marina Design Management", (APP/"modules.txt").read_text().splitlines())
        install=(APP/"sales_forecasting"/"install.py").read_text()
        self.assertIn("design_after_migrate()",install)
        self.assertIn("design_after_install()",install)
        self.assertLess(install.index("design_after_migrate()"),
                        install.index("ensure_independent_workspaces()",
                                     install.index("def app_after_migrate")))
    
    def test_top_level_workspaces(self):
        for ws in ["Marina Design Management","DC Dispatch","POS Reconciliation",
                   "Sales Forecasting","Marina Calendar","Cycle Count",
                   "Stock Auto Allocation","Stock Transfer Audit","SOP Management"]:
            match=list(APP.rglob("workspace/"+ws.lower().replace(" ","_")+"/*.json"))
            self.assertTrue(match, ws)
            self.assertEqual(json.loads(match[0].read_text())["parent_page"],"")

    def test_module_ownership_and_packaging(self):
        owner = DESIGN / "setup" / "module_ownership.py"
        self.assertTrue(owner.is_file())
        content = owner.read_text()
        self.assertIn('Module Def', content)
        self.assertIn('marina_custom_apps', content)
        self.assertIn('before_migrate', (APP / "hooks.py").read_text())
        from setuptools import find_packages
        packages = set(find_packages(where=str(ROOT)))
        for pkg in (
            "marina_custom_apps.design_management",
            "marina_custom_apps.design_management.security",
            "marina_custom_apps.design_management.setup",
            "marina_custom_apps.marina_design_management",
            "marina_custom_apps.marina_design_management.doctype",
            "marina_custom_apps.marina_design_management.doctype.design_code",
        ):
            self.assertIn(pkg, packages)
        self.assertTrue((ROOT / "MANIFEST.in").is_file())

    def test_design_select_options_and_role_seeds(self):
        """Select definitions must use actual newlines, not literal backslash-n."""
        for schema in sorted((MODULE / "doctype").glob("*/*.json")):
            definition = json.loads(schema.read_text())
            for field in definition.get("fields", []):
                if field.get("fieldtype") != "Select":
                    continue
                options = field.get("options") or ""
                with self.subTest(doctype=definition.get("name"), field=field.get("fieldname")):
                    self.assertNotIn("\\n", options, "Escape sequences must be real line breaks")
                    default = field.get("default")
                    if default not in (None, ""):
                        self.assertIn(str(default), options.split("\n"))

        org_source = (DESIGN / "security" / "organization.py").read_text()
        tree = ast.parse(org_source)
        groups = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "DEFAULT_GROUPS"
                    for t in node.targets)
        )
        role_schema = json.loads(
            (MODULE / "doctype" / "design_module_role" / "design_module_role.json").read_text()
        )
        group_field = next(
            field for field in role_schema["fields"]
            if field.get("fieldname") == "responsibility_group"
        )
        allowed = set(group_field["options"].split("\n"))
        self.assertTrue({"Other", "Buying"} <= allowed)
        self.assertTrue(set(groups.values()) <= allowed)

    def test_mood_board_import_list_and_document_permissions(self):
        source = (DESIGN / "security" / "permissions.py").read_text()
        # A System Manager must always see imported data even if no Design
        # Module Role has been assigned on a freshly installed demo.
        self.assertIn('def _design_system_admin(user):', source)
        self.assertIn('user == "Administrator" or "System Manager" in frappe.get_roles(user)', source)
        self.assertIn('if _design_system_admin(user) or has_overall_visibility(user):', source)
        # An authorized importer can view a new board while no active team
        # exists; once assigned, visibility follows custody instead.
        self.assertIn('"((`tabMood Board`.owner="+esc+" AND NOT EXISTS ("', source)
        self.assertIn('if doc.owner == user and not any(', source)
        self.assertIn('"parentfield":"r22_team_assignments"', source)
        # Match list query's linked Design Code / team visibility on open.
        self.assertIn('assigned_scope_sql(user,"d")', source)
        self.assertIn('"SELECT 1 FROM `tabDesign Code` d WHERE d.mood_board=%s AND "', source)
        self.assertIn('" LIMIT 1"', source)
        self.assertIn('if can_doctype("Mood Board","read",user) is False:', source)

    def test_no_old_imports_or_wrong_namespace(self):
        bad=[]
        for root in (DESIGN,MODULE):
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in (".py",".js",".json",".html"):
                    continue
                if path.name=="legacy_hooks.py":
                    continue
                raw=path.read_text(encoding="utf8")
                if "marina_custom_apps.marina_custom_apps." in raw:
                    bad.append(str(path.relative_to(ROOT))+": doubled package namespace")
                if "marina_custom_apps/marina_custom_apps/" in raw:
                    bad.append(str(path.relative_to(ROOT))+": doubled file-path namespace")

                if "marina_design_management.marina_design_management." in raw:
                    bad.append(str(path.relative_to(ROOT))+": old app namespace")
                if "/assets/marina_design_management/" in raw:
                    bad.append(str(path.relative_to(ROOT))+": old asset namespace")
                if path.suffix==".py":
                    try: ast.parse(raw)
                    except SyntaxError as e:
                        bad.append(str(path.relative_to(ROOT))+f": {e}")
        self.assertFalse(bad, "\\n".join(bad))
 
if __name__ == "__main__":
    unittest.main()
