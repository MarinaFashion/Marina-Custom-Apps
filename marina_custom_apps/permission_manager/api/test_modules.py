from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from marina_custom_apps.permission_manager.api.modules import _module_catalogue, _set_module_availability


class TestUserModuleManagement(TestCase):
	@patch("marina_custom_apps.permission_manager.api.modules.get_modules_from_all_apps")
	def test_module_catalogue_is_unique_and_grouped_by_app(self, get_modules):
		get_modules.return_value = [
			{"module_name": "Stock", "app": "erpnext"},
			{"module_name": "Core", "app": "frappe"},
			{"module_name": "Stock", "app": "erpnext"},
		]

		self.assertEqual(
			_module_catalogue(),
			[
				{"module": "Stock", "app": "erpnext"},
				{"module": "Core", "app": "frappe"},
			],
		)

	@patch("marina_custom_apps.permission_manager.api.modules.now", return_value="2026-09-18 12:00:00")
	@patch.object(frappe, "clear_cache")
	@patch.object(frappe, "get_doc")
	@patch.object(frappe.db, "set_value")
	@patch.object(frappe.db, "exists", return_value=None)
	def test_blocking_module_inserts_only_selected_module(
		self,
		exists,
		set_value,
		get_doc,
		clear_cache,
		_now,
	):
		child = Mock()
		get_doc.return_value = child

		changed = _set_module_availability("user@example.com", "Stock", available=False)

		self.assertTrue(changed)
		exists.assert_called_once()
		get_doc.assert_called_once_with(
			{
				"doctype": "Block Module",
				"parent": "user@example.com",
				"parenttype": "User",
				"parentfield": "block_modules",
				"module": "Stock",
			}
		)
		child.insert.assert_called_once_with(ignore_permissions=True)
		set_value.assert_called_once()
		clear_cache.assert_called_once_with(user="user@example.com")

	@patch("marina_custom_apps.permission_manager.api.modules.now", return_value="2026-09-18 12:00:00")
	@patch.object(frappe, "clear_cache")
	@patch.object(frappe.db, "set_value")
	@patch.object(frappe.db, "delete")
	@patch.object(frappe.db, "exists", return_value="BLOCK-MODULE-ROW")
	def test_allowing_module_removes_only_matching_block(
		self,
		exists,
		delete,
		set_value,
		clear_cache,
		_now,
	):
		changed = _set_module_availability("user@example.com", "Stock", available=True)

		self.assertTrue(changed)
		exists.assert_called_once()
		delete.assert_called_once_with(
			"Block Module",
			{
				"parenttype": "User",
				"parent": "user@example.com",
				"module": "Stock",
			},
		)
		set_value.assert_called_once()
		clear_cache.assert_called_once_with(user="user@example.com")
