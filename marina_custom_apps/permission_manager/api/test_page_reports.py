from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe

from marina_custom_apps.permission_manager.api.page_reports import _save_resource_role


class TestPageReportPermissionManagement(TestCase):
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
