from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from marina_custom_apps.permission_manager.api.user_permissions import (
	_as_bool,
	_rule_filters,
	get_current_user_permissions,
	save_current_user_permissions,
	save_user_permission_values,
	save_user_permission_users,
)


class TestBulkUserPermissions(TestCase):
	def test_scope_boolean_accepts_frappe_request_values(self):
		self.assertTrue(_as_bool(True))
		self.assertTrue(_as_bool(1))
		self.assertTrue(_as_bool("1"))
		self.assertTrue(_as_bool("true"))
		self.assertFalse(_as_bool(False))
		self.assertFalse(_as_bool(0))
		self.assertFalse(_as_bool("0"))
		self.assertFalse(_as_bool("false"))

	def test_rule_filters_preserve_exact_scope(self):
		self.assertEqual(
			_rule_filters("Warehouse", "Stores - MA", False, "Stock Entry"),
			{
				"allow": "Warehouse",
				"for_value": "Stores - MA",
				"apply_to_all_doctypes": 0,
				"applicable_for": "Stock Entry",
			},
		)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_rule",
		return_value=(True, ""),
	)
	@patch.object(frappe, "delete_doc")
	@patch.object(frappe, "get_all")
	def test_existing_permission_can_be_removed_from_inactive_user(
		self,
		get_all,
		delete_doc,
		_validate_rule,
		_only_system_manager,
	):
		def rows(doctype, **kwargs):
			if doctype == "User":
				return [SimpleNamespace(name="inactive@example.com", enabled=0)]
			if doctype == "User Permission":
				return [
					SimpleNamespace(
						name="UP-0001",
						user="inactive@example.com",
						is_default=0,
					)
				]
			return []

		get_all.side_effect = rows
		result = save_user_permission_users(
			allow="Warehouse",
			for_value="Stores - MA",
			apply_to_all_doctypes=1,
			applicable_for=None,
			is_default=0,
			changes=[{"user": "inactive@example.com", "assigned": 0}],
		)

		self.assertEqual(result, {"created": 0, "updated": 0, "deleted": 1})
		delete_doc.assert_called_once_with(
			"User Permission", "UP-0001", ignore_permissions=True
		)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_rule",
		return_value=(True, ""),
	)
	@patch.object(frappe, "get_all")
	def test_new_permission_is_blocked_for_inactive_user(
		self,
		get_all,
		_validate_rule,
		_only_system_manager,
	):
		get_all.side_effect = lambda doctype, **kwargs: (
			[SimpleNamespace(name="inactive@example.com", enabled=0)]
			if doctype == "User"
			else []
		)

		with self.assertRaises(frappe.ValidationError):
			save_user_permission_users(
				allow="Warehouse",
				for_value="Stores - MA",
				apply_to_all_doctypes=1,
				applicable_for=None,
				is_default=0,
				changes=[{"user": "inactive@example.com", "assigned": 1}],
			)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_user",
		return_value=SimpleNamespace(
			name="active@example.com", full_name="Active User", enabled=1
		),
	)
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_allow_scope",
		return_value=(False, "Sales Invoice"),
	)
	@patch.object(frappe.db, "exists", return_value=True)
	@patch.object(frappe, "get_doc")
	@patch.object(frappe, "get_all", return_value=[])
	def test_missing_exact_permission_is_created_for_active_user(
		self,
		get_all,
		get_doc,
		db_exists,
		_validate_allow_scope,
		_validate_user,
		_only_system_manager,
	):
		doc = SimpleNamespace(insert=lambda **kwargs: None)
		get_doc.return_value = doc

		result = save_user_permission_values(
			user="active@example.com",
			allow="POS Profile",
			apply_to_all_doctypes=0,
			applicable_for="Sales Invoice",
			changes=[
				{"for_value": "POS19 - Makkah", "assigned": 1, "is_default": 1}
			],
		)

		self.assertEqual(result, {"created": 1, "updated": 0, "deleted": 0})
		get_doc.assert_called_once_with(
			{
				"doctype": "User Permission",
				"user": "active@example.com",
				"allow": "POS Profile",
				"for_value": "POS19 - Makkah",
				"apply_to_all_doctypes": 0,
				"applicable_for": "Sales Invoice",
				"is_default": 1,
			}
		)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_user",
		return_value=SimpleNamespace(
			name="inactive@example.com", full_name="Inactive User", enabled=0
		),
	)
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_allow_scope",
		return_value=(True, ""),
	)
	@patch.object(frappe, "get_all", return_value=[])
	def test_missing_exact_permission_is_blocked_for_inactive_user_in_value_mode(
		self,
		get_all,
		_validate_allow_scope,
		_validate_user,
		_only_system_manager,
	):
		with self.assertRaises(frappe.ValidationError):
			save_user_permission_values(
				user="inactive@example.com",
				allow="Warehouse",
				apply_to_all_doctypes=1,
				applicable_for=None,
				changes=[{"for_value": "Stores - MA", "assigned": 1, "is_default": 0}],
			)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_user",
		return_value=SimpleNamespace(
			name="inactive@example.com", full_name="Inactive User", enabled=0
		),
	)
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_allow_scope",
		return_value=(True, ""),
	)
	@patch.object(frappe, "delete_doc")
	@patch.object(frappe, "get_all")
	def test_exact_permission_can_be_deleted_for_inactive_user_in_value_mode(
		self,
		get_all,
		delete_doc,
		_validate_allow_scope,
		_validate_user,
		_only_system_manager,
	):
		get_all.side_effect = lambda doctype, **kwargs: (
			[
				SimpleNamespace(
					name="UP-0002", for_value="Stores - MA", is_default=0
				)
			]
			if doctype == "User Permission"
			else []
		)

		result = save_user_permission_values(
			user="inactive@example.com",
			allow="Warehouse",
			apply_to_all_doctypes=1,
			applicable_for=None,
			changes=[{"for_value": "Stores - MA", "assigned": 0, "is_default": 0}],
		)

		self.assertEqual(result, {"created": 0, "updated": 0, "deleted": 1})
		delete_doc.assert_called_once_with(
			"User Permission", "UP-0002", ignore_permissions=True
		)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch.object(frappe, "get_meta", return_value=SimpleNamespace(title_field="title"))
	@patch.object(frappe.db, "exists", return_value=True)
	@patch.object(frappe, "get_all")
	def test_current_permissions_include_user_status_and_value_label(
		self, get_all, db_exists, get_meta, _only_system_manager
	):
		def rows(doctype, **kwargs):
			if doctype == "User":
				return [frappe._dict(name="inactive@example.com", full_name="Inactive User", enabled=0)]
			if doctype == "User Permission":
				return [
					frappe._dict(
						name="UP-0003",
						user="inactive@example.com",
						allow="POS Profile",
						for_value="POS19",
						apply_to_all_doctypes=0,
						applicable_for="Sales Invoice",
						is_default=0,
					)
				]
			if doctype == "POS Profile":
				return [frappe._dict(name="POS19", title="Makkah Mall")]
			return []

		get_all.side_effect = rows
		result = get_current_user_permissions(user_status="Inactive")

		self.assertEqual(result["rows"][0]["label"], "Makkah Mall")
		self.assertFalse(result["rows"][0]["enabled"])
		self.assertEqual(result["rows"][0]["applicable_for"], "Sales Invoice")

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch.object(frappe, "delete_doc")
	@patch.object(frappe, "get_all")
	def test_review_can_delete_existing_permission_for_inactive_user(
		self, get_all, delete_doc, _only_system_manager
	):
		permission = frappe._dict(
			name="UP-0004",
			user="inactive@example.com",
			allow="POS Profile",
			for_value="POS19",
			apply_to_all_doctypes=0,
			applicable_for="Sales Invoice",
			is_default=0,
		)

		def rows(doctype, **kwargs):
			if doctype == "User":
				return [frappe._dict(name="inactive@example.com")]
			if doctype == "User Permission":
				return [permission]
			return []

		get_all.side_effect = rows
		result = save_current_user_permissions([{"name": "UP-0004", "deleted": 1}])

		self.assertEqual(result, {"updated": 0, "deleted": 1})
		delete_doc.assert_called_once_with("User Permission", "UP-0004", ignore_permissions=True)

	@patch("marina_custom_apps.permission_manager.api.user_permissions._only_system_manager")
	@patch(
		"marina_custom_apps.permission_manager.api.user_permissions._validate_allow_scope",
		return_value=(False, "Sales Invoice"),
	)
	@patch.object(frappe, "get_all")
	def test_review_blocks_overlapping_default_permissions(
		self, get_all, _validate_allow_scope, _only_system_manager
	):
		first = frappe._dict(
			name="UP-0005",
			user="active@example.com",
			allow="POS Profile",
			for_value="POS19",
			apply_to_all_doctypes=0,
			applicable_for="Sales Invoice",
			is_default=0,
		)
		second = frappe._dict(
			name="UP-0006",
			user="active@example.com",
			allow="POS Profile",
			for_value="POS20",
			apply_to_all_doctypes=0,
			applicable_for="Sales Invoice",
			is_default=1,
		)
		permission_calls = 0

		def rows(doctype, **kwargs):
			nonlocal permission_calls
			if doctype == "User":
				return [frappe._dict(name="active@example.com")]
			if doctype == "User Permission":
				permission_calls += 1
				return [first] if permission_calls == 1 else [first, second]
			return []

		get_all.side_effect = rows
		with self.assertRaises(frappe.ValidationError):
			save_current_user_permissions(
				[
					{
						"name": "UP-0005",
						"apply_to_all_doctypes": 0,
						"applicable_for": "Sales Invoice",
						"is_default": 1,
					}
				]
			)
