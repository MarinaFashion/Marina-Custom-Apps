from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import call, patch

import frappe

from marina_custom_apps.permission_manager.api.workspaces import _replace_workspace_roles, _role_gate_access


class TestWorkspaceAccessManagement(TestCase):
	def test_public_workspace_without_roles_is_open(self):
		allowed, reason, matching = _role_gate_access(
			public=True,
			for_user=None,
			user="user@example.com",
			user_roles={"Stock User"},
			allowed_roles=set(),
		)

		self.assertTrue(allowed)
		self.assertEqual(reason, "Open to all Desk users")
		self.assertEqual(matching, [])

	def test_public_workspace_requires_a_matching_role(self):
		allowed, _reason, matching = _role_gate_access(
			public=True,
			for_user=None,
			user="user@example.com",
			user_roles={"Stock User", "Purchase User"},
			allowed_roles={"Purchase User", "Accounts User"},
		)

		self.assertTrue(allowed)
		self.assertEqual(matching, ["Purchase User"])

	def test_automatic_desk_role_opens_public_workspace(self):
		allowed, reason, _matching = _role_gate_access(
			public=True,
			for_user=None,
			user="user@example.com",
			user_roles={"Stock User"},
			allowed_roles={"Desk User"},
		)

		self.assertTrue(allowed)
		self.assertEqual(reason, "Open to all Desk users")

	def test_workspace_manager_bypasses_public_role_gate(self):
		allowed, reason, matching = _role_gate_access(
			public=True,
			for_user=None,
			user="manager@example.com",
			user_roles={"Workspace Manager"},
			allowed_roles={"Accounts User"},
		)

		self.assertTrue(allowed)
		self.assertEqual(reason, "Workspace Manager")
		self.assertEqual(matching, ["Workspace Manager"])

	def test_private_workspace_is_only_for_its_owner(self):
		owner_access = _role_gate_access(
			public=False,
			for_user="owner@example.com",
			user="owner@example.com",
			user_roles=set(),
			allowed_roles={"Accounts User"},
		)
		other_access = _role_gate_access(
			public=False,
			for_user="owner@example.com",
			user="other@example.com",
			user_roles={"Accounts User"},
			allowed_roles={"Accounts User"},
		)

		self.assertTrue(owner_access[0])
		self.assertFalse(other_access[0])

	@patch.object(frappe.db, "set_value")
	@patch.object(frappe, "get_doc")
	@patch.object(frappe.db, "delete")
	@patch.object(frappe, "get_all", return_value=["Stock User"])
	def test_replacing_workspace_roles_updates_only_role_children(
		self,
		_get_all,
		delete,
		get_doc,
		set_value,
	):
		get_doc.side_effect = lambda values: SimpleNamespace(
			insert=lambda **kwargs: inserted.append((values, kwargs))
		)
		inserted = []

		changed = _replace_workspace_roles("Stock", {"Purchase User", "Stock User"})

		self.assertTrue(changed)
		delete.assert_called_once_with(
			"Has Role",
			{"parenttype": "Workspace", "parent": "Stock", "parentfield": "roles"},
		)
		self.assertEqual(
			[item[0]["role"] for item in inserted],
			["Purchase User", "Stock User"],
		)
		set_value.assert_called_once()

	@patch.object(frappe.db, "set_value")
	@patch.object(frappe, "get_doc")
	@patch.object(frappe.db, "delete")
	@patch.object(frappe, "get_all", return_value=["Accounts User"])
	def test_unchanged_workspace_roles_do_not_write(
		self,
		_get_all,
		delete,
		get_doc,
		set_value,
	):
		changed = _replace_workspace_roles("Accounts", {"Accounts User"})

		self.assertFalse(changed)
		delete.assert_not_called()
		get_doc.assert_not_called()
		set_value.assert_not_called()
