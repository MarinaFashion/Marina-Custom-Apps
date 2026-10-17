"""Regression guard: Single Reconciliation Workspace never sets invalid Form view."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe
from marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace import execute


class _Workspace:
    def __init__(self, view):
        self.shortcuts = [frappe._dict(
            type="DocType",
            link_to="POS Reconciliation Run",
            label="Reconciliation Control",
            doc_view=view,
        )]
        self.links = [
            frappe._dict(link_to="POS Reconciliation Execution"),
            frappe._dict(link_to="POS Reconciliation Period Lock"),
        ]
        self.content = json.dumps([
            {"type": "shortcut", "data": {"shortcut_name": "Reconciliation Control"}},
            {"type": "shortcut", "data": {"shortcut_name": "Execution History"}},
            {"type": "shortcut", "data": {"shortcut_name": "Period Locks"}},
        ])
        self.flags = frappe._dict()
        self.saved = False

    def get(self, field):
        return getattr(self, field)

    def save(self):
        assert self.shortcuts[0].doc_view in ("", "List", "Report Builder",
                                                "Dashboard", "Tree", "New",
                                                "Calendar", "Kanban")
        self.saved = True


class TestSingleWorkspaceShortcut(TestCase):
    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.clear_cache")
    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.get_doc")
    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.db.exists", return_value=True)
    def test_invalid_form_view_is_corrected(self, exists, get_doc, clear_cache):
        workspace = _Workspace("Form")
        get_doc.return_value = workspace
        execute()
        self.assertTrue(workspace.saved)
        self.assertEqual(workspace.shortcuts[0].doc_view, "")

    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.clear_cache")
    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.get_doc")
    @patch("marina_custom_apps.patches.v0_53_1.ensure_pos_single_workspace.frappe.db.exists", return_value=True)
    def test_correct_workspace_is_not_rewritten(self, exists, get_doc, clear_cache):
        workspace = _Workspace("")
        get_doc.return_value = workspace
        execute()
        self.assertFalse(workspace.saved)
