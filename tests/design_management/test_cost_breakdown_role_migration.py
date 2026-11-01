"""Regression tests for a non-destructive Cost Breakdown role migration.

The demo site may have orphaned legacy Design Module permission child rows.
Never save/revalidate that entire parent while adding the new grants.
"""
import ast
import json
from pathlib import Path
import re
import sys
import types
from unittest import TestCase, main
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / "marina_custom_apps"
SOURCE = ROOT / "design_management" / "setup" / "module_role_defaults.py"
ACTION_JSON = (ROOT / "marina_design_management" / "doctype" /
               "design_module_action_permission" / "design_module_action_permission.json")


class FakeDatabase:
    def __init__(self):
        self.roles = {"Merchandiser", "Head Of Merchandisers",
                      "Buying Manager", "Administrator"}
        self.entries = [
            {"doctype": "Design Module DocType Permission",
             "parent": "Merchandiser", "parenttype": "Design Module Role",
             "parentfield": "doctype_permissions", "idx": 4,
             "resource_doctype": "Design Milestone Record", "read": 1},
            {"doctype": "Design Module DocType Permission",
             "parent": "Merchandiser", "parenttype": "Design Module Role",
             "parentfield": "doctype_permissions", "idx": 7,
             "resource_doctype": "Design Delay Reason", "read": 1},
            # Explicitly customized permission must never be overwritten.
            {"doctype": "Design Module DocType Permission",
             "parent": "Head Of Merchandisers", "parenttype": "Design Module Role",
             "parentfield": "doctype_permissions", "idx": 2,
             "resource_doctype": "Design Cost Breakdown",
             "read": 1, "create": 0, "write": 0},
        ]

    def exists(self, doctype, filters):
        if doctype == "DocType":
            return filters == "Design Cost Breakdown"
        if doctype == "Design Module Role":
            return filters in self.roles
        if isinstance(filters, dict):
            for row in self.entries:
                if row["doctype"] == doctype and all(row.get(k) == v
                                                      for k, v in filters.items()):
                    return True
        return False

    def sql(self, query, values):
        typ = re.search(r"FROM `tab([^`]+)`", query).group(1)
        role, parenttype, parentfield = values
        values = [row["idx"] for row in self.entries
                  if row["doctype"] == typ and row["parent"] == role and
                  row["parenttype"] == parenttype and row["parentfield"] == parentfield]
        return [(max(values, default=0),)]


class FakeFrappe:
    def __init__(self):
        self.db = FakeDatabase()
        self.cache_cleared = []

    def get_doc(self, properties):
        if not isinstance(properties, dict):
            raise AssertionError("Migration must never load/save existing role parents")
        frappe = self
        class Child:
            def db_insert(self):
                row = dict(properties)
                row["name"] = "NEW-" + str(len(frappe.db.entries) + 1)
                frappe.db.entries.append(row)
            def save(self, *args, **kwargs):
                raise AssertionError("No save permitted during migration")
        return Child()

    def clear_document_cache(self, doctype, name):
        self.cache_cleared.append((doctype, name))


def extract_sync(fake):
    tree = ast.parse(SOURCE.read_text())
    target = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "sync_cost_breakdown_permissions")
    namespace = {"frappe": fake}
    exec(compile(ast.Module(body=[target], type_ignores=[]),
                 str(SOURCE), "exec"), namespace)
    return namespace["sync_cost_breakdown_permissions"]


class CostRoleMigrationTests(TestCase):
    def test_handles_orphans_without_revalidating_parent_and_is_idempotent(self):
        fake = FakeFrappe()
        sync = extract_sync(fake)
        organizations = types.ModuleType("marina_custom_apps.design_management.security.organization")
        cache_clear_calls = []
        organizations.clear_role_cache = lambda: cache_clear_calls.append(True)
        with patch.dict(sys.modules, {
            "marina_custom_apps.design_management.security.organization": organizations
        }):
            sync()
            snapshot = [dict(row) for row in fake.db.entries]
            sync()
        self.assertEqual(fake.db.entries, snapshot)
        self.assertEqual(len(fake.db.entries), 2 + 1 + 5)
        self.assertEqual(len(cache_clear_calls), 1)
        legacy = [row for row in fake.db.entries
                  if row.get("resource_doctype") in
                  ("Design Milestone Record", "Design Delay Reason")]
        self.assertEqual(len(legacy), 2)
        self.assertEqual([r["idx"] for r in legacy], [4, 7])
        custom = next(row for row in fake.db.entries
                      if row.get("parent") == "Head Of Merchandisers"
                      and row.get("resource_doctype") == "Design Cost Breakdown")
        self.assertEqual((custom["read"], custom["create"], custom["write"]), (1, 0, 0))
        buyer = next(row for row in fake.db.entries
                     if row.get("parent") == "Buying Manager"
                     and row.get("resource_doctype") == "Design Cost Breakdown")
        self.assertEqual((buyer["read"], buyer["create"], buyer["write"]), (1, 0, 0))
        action_roles = {r["parent"] for r in fake.db.entries
                        if r.get("action_key") == "Approve Design Cost Breakdown"}
        self.assertEqual(action_roles, {"Buying Manager", "Administrator"})

    def test_action_is_real_select_option(self):
        meta = json.loads(ACTION_JSON.read_text())
        options = next(f["options"] for f in meta["fields"]
                       if f["fieldname"] == "action_key")
        self.assertIn("Approve Design Cost Breakdown", options.split("\n"))
        self.assertNotIn("\\nApprove Design Cost Breakdown", options)


if __name__ == "__main__":
    main()
