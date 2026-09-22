from collections import defaultdict
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe

from marina_custom_apps.permission_manager.api.page_reports import (
	_replace_open_resource_roles,
	_save_resource_role,
)


class TestPageReportPermissionManagement(TestCase):
	@patch("marina_custom_apps.permission_manager.api.page_reports._custom_role_documents", return_value={})
	@patch("marina_custom_apps.permission_manager.api.page_reports._roles_by_parent")
	@patch.object(frappe, "get_doc")
	@patch.object(frappe.db, "get_value", return_value="Purchase Invoice")
	def test_bulk_restriction_creates_exact_role_override(
		self,
		_get_value,
		get_doc,
		roles_by_parent,
		_custom_documents,
	):
		roles_by_parent.side_effect = [defaultdict(set), defaultdict(set)]
		custom_doc = Mock()
		get_doc.return_value = custom_doc

		result = _replace_open_resource_roles(
			"Report",
			["Accounts Payable Summary"],
			{"Stock Manager", "System Manager"},
		)

		self.assertEqual(result, {"updated_rows": 1, "skipped_rows": 0})
		custom_doc.set.assert_called_once_with("roles", [])
		self.assertEqual(
			custom_doc.append.call_args_list,
			[
				call("roles", {"role": "Stock Manager"}),
				call("roles", {"role": "System Manager"}),
			],
		)
		custom_doc.insert.assert_called_once_with(ignore_permissions=True)

	@patch("marina_custom_apps.permission_manager.api.page_reports._custom_role_documents", return_value={})
	@patch("marina_custom_apps.permission_manager.api.page_reports._roles_by_parent")
	@patch.object(frappe, "get_doc")
	def test_bulk_restriction_skips_resource_that_is_no_longer_open(
		self,
		get_doc,
		roles_by_parent,
		_custom_documents,
	):
		roles_by_parent.side_effect = [
			defaultdict(set, {"Accounts Payable": {"Accounts Manager"}}),
			defaultdict(set),
		]

		result = _replace_open_resource_roles(
			"Report",
			["Accounts Payable"],
			{"Stock Manager"},
		)

		self.assertEqual(result, {"updated_rows": 0, "skipped_rows": 1})
		get_doc.assert_not_called()

	@patch("marina_custom_apps.permission_manager.api.page_reports._custom_role_documents")
	@patch("marina_custom_apps.permission_manager.api.page_reports._roles_by_parent")
	@patch.object(frappe, "get_doc")
	def test_bulk_restriction_replaces_custom_automatic_role(
		self,
		get_doc,
		roles_by_parent,
		custom_documents,
	):
		custom_documents.return_value = {
			"Accounts Receivable Summary": SimpleNamespace(name="CUSTOM-ROLE-1")
		}
		roles_by_parent.side_effect = [
			defaultdict(set),
			defaultdict(set, {"CUSTOM-ROLE-1": {"All", "Accounts Manager"}}),
		]
		custom_doc = Mock()
		get_doc.return_value = custom_doc

		result = _replace_open_resource_roles(
			"Report",
			["Accounts Receivable Summary"],
			{"Stock Manager"},
		)

		self.assertEqual(result, {"updated_rows": 1, "skipped_rows": 0})
		custom_doc.set.assert_called_once_with("roles", [])
		custom_doc.append.assert_called_once_with("roles", {"role": "Stock Manager"})
		custom_doc.save.assert_called_once_with(ignore_permissions=True)

	@patch.object(frappe, "get_all", return_value=[])
	@patch.object(frappe.db, "get_value", return_value=None)
	def test_open_to_all_resource_needs_no_override_when_allowed(self, get_value, get_all):
		changed = _save_resource_role("Page", "test-page", "Stock User", allowed=True)

		self.assertFalse(changed)
		get_value.assert_called_once_with("Custom Role", {"page": "test-page"}, "name")
		get_all.assert_called_once()

	@patch.object(frappe, "get_doc")
	@patch.object(frappe, "get_all", return_value=["Buying User", "Stock User"])
	@patch.object(frappe.db, "get_value", return_value=None)
	def test_new_override_starts_from_standard_roles(self, _get_value, _get_all, get_doc):
		custom_doc = Mock()
		get_doc.return_value = custom_doc

		changed = _save_resource_role("Page", "test-page", "Accounts User", allowed=True)

		self.assertTrue(changed)
		self.assertEqual(
			custom_doc.append.call_args_list,
			[
				call("roles", {"role": "Accounts User"}),
				call("roles", {"role": "Buying User"}),
				call("roles", {"role": "Stock User"}),
			],
		)
		custom_doc.insert.assert_called_once_with(ignore_permissions=True)

	@patch.object(frappe, "delete_doc")
	@patch.object(frappe, "get_doc")
	@patch.object(frappe, "get_all", return_value=["Buying User", "Stock User"])
	@patch.object(frappe.db, "get_value", return_value="CUSTOM-ROLE-1")
	def test_matching_standard_roles_removes_override(
		self,
		_get_value,
		_get_all,
		get_doc,
		delete_doc,
	):
		get_doc.return_value.roles = [
			SimpleNamespace(role="Accounts User"),
			SimpleNamespace(role="Buying User"),
			SimpleNamespace(role="Stock User"),
		]

		changed = _save_resource_role("Page", "test-page", "Accounts User", allowed=False)

		self.assertTrue(changed)
		delete_doc.assert_called_once_with("Custom Role", "CUSTOM-ROLE-1", ignore_permissions=True)
