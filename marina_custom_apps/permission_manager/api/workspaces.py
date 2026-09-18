from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.permissions import AUTOMATIC_ROLES
from frappe.utils import now

MAX_WORKSPACE_ROLES = 500
STANDARD_USERS = ("Guest",)


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _get_workspace(workspace: str) -> Any:
	if not workspace:
		frappe.throw(_("Please select a Workspace."))

	if not frappe.db.exists("Workspace", workspace):
		frappe.throw(_("Please select a valid Workspace."))

	return frappe.get_doc("Workspace", workspace)


def _custom_page_roles(workspace: str) -> set[str]:
	"""Return roles added through Custom Role for a Page with the workspace name.

	Frappe includes these roles when evaluating Workspace access, so the manager must
	show them even though it only edits the Workspace's own Roles table.
	"""
	custom_name = frappe.db.get_value("Custom Role", {"page": workspace}, "name")
	if not custom_name:
		return set()

	return set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "Custom Role", "parent": custom_name},
			pluck="role",
		)
	)


def _active_users_with_roles() -> tuple[list[Any], dict[str, set[str]]]:
	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ("not in", STANDARD_USERS),
		},
		fields=["name", "full_name"],
		order_by="full_name asc, name asc",
	)
	user_names = [user.name for user in users]
	roles_by_user: dict[str, set[str]] = defaultdict(set)
	if user_names:
		for row in frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "parent": ("in", user_names)},
			fields=["parent", "role"],
		):
			roles_by_user[row.parent].add(row.role)

	return users, roles_by_user


def _role_gate_access(
	*,
	public: bool,
	for_user: str | None,
	user: str,
	user_roles: set[str],
	allowed_roles: set[str],
) -> tuple[bool, str, list[str]]:
	if not public:
		allowed = bool(for_user and user == for_user)
		return allowed, _("Private owner") if allowed else _("Private workspace"), []

	if "Workspace Manager" in user_roles:
		return True, _("Workspace Manager"), ["Workspace Manager"]

	if not allowed_roles or allowed_roles.intersection({"All", "Desk User"}):
		return True, _("Open to all Desk users"), []

	matches = sorted(user_roles.intersection(allowed_roles))
	if matches:
		return True, _("Matching role"), matches

	return False, _("No matching role"), []


@frappe.whitelist()
def get_workspace_access(workspace: str) -> dict[str, Any]:
	"""Return native Workspace roles and active users matching the role gate."""
	_only_system_manager()
	doc = _get_workspace(workspace)
	native_roles = {row.role for row in doc.roles}
	page_override_roles = _custom_page_roles(doc.name)
	effective_roles = native_roles.union(page_override_roles)

	users, roles_by_user = _active_users_with_roles()
	role_counts: dict[str, int] = defaultdict(int)
	for roles in roles_by_user.values():
		for role in roles:
			role_counts[role] += 1

	roles = frappe.get_all(
		"Role",
		filters={
			"disabled": 0,
			"name": ("not in", tuple(AUTOMATIC_ROLES)),
		},
		pluck="name",
		order_by="name asc",
	)

	user_rows = []
	for user in users:
		user_roles = roles_by_user[user.name]
		allowed, reason, matching_roles = _role_gate_access(
			public=bool(doc.public),
			for_user=doc.for_user,
			user=user.name,
			user_roles=user_roles,
			allowed_roles=effective_roles,
		)
		user_rows.append(
			{
				"user": user.name,
				"full_name": user.full_name or user.name,
				"roles": sorted(user_roles),
				"allowed": allowed,
				"reason": reason,
				"matching_roles": matching_roles,
			}
		)

	return {
		"workspace": {
			"name": doc.name,
			"title": doc.title or doc.label or doc.name,
			"module": doc.module,
			"public": bool(doc.public),
			"for_user": doc.for_user,
			"is_hidden": bool(doc.is_hidden),
			"editable": bool(doc.public and not doc.for_user),
		},
		"roles": [
			{
				"role": role,
				"assigned": role in native_roles,
				"page_override": role in page_override_roles,
				"active_users": role_counts[role],
			}
			for role in roles
		],
		"users": user_rows,
		"page_override_roles": sorted(page_override_roles),
	}


def _replace_workspace_roles(workspace: str, roles: set[str]) -> bool:
	existing = set(
		frappe.get_all(
			"Has Role",
			filters={
				"parenttype": "Workspace",
				"parent": workspace,
				"parentfield": "roles",
			},
			pluck="role",
		)
	)
	if roles == existing:
		return False

	frappe.db.delete(
		"Has Role",
		{
			"parenttype": "Workspace",
			"parent": workspace,
			"parentfield": "roles",
		},
	)
	for role in sorted(roles):
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": workspace,
				"parenttype": "Workspace",
				"parentfield": "roles",
				"role": role,
			}
		).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Workspace",
		workspace,
		{"modified": now(), "modified_by": frappe.session.user},
		update_modified=False,
	)
	return True


@frappe.whitelist()
def save_workspace_roles(workspace: str, roles: str | list[str]) -> dict[str, Any]:
	"""Replace the native allowed-role list of one public Workspace."""
	_only_system_manager()
	doc = _get_workspace(workspace)
	if not doc.public or doc.for_user:
		frappe.throw(
			_("Private user workspaces cannot be assigned through roles. Convert the Workspace to Public first.")
		)

	parsed_roles = frappe.parse_json(roles) if isinstance(roles, str) else roles
	if not isinstance(parsed_roles, list) or any(not isinstance(role, str) or not role for role in parsed_roles):
		frappe.throw(_("Workspace roles must be provided as a list."))
	if len(parsed_roles) > MAX_WORKSPACE_ROLES:
		frappe.throw(_("A maximum of {0} roles can be assigned.").format(MAX_WORKSPACE_ROLES))
	if len(parsed_roles) != len(set(parsed_roles)):
		frappe.throw(_("Each role can appear only once."))
	if set(parsed_roles).intersection(AUTOMATIC_ROLES):
		frappe.throw(_("Automatic roles cannot be assigned to a Workspace here."))

	valid_roles = set(
		frappe.get_all(
			"Role",
			filters={"disabled": 0, "name": ("in", parsed_roles or [""])},
			pluck="name",
		)
	)
	if valid_roles != set(parsed_roles):
		frappe.throw(_("One or more selected roles are disabled or invalid."))

	updated = _replace_workspace_roles(doc.name, valid_roles)
	if updated:
		users = frappe.get_all(
			"User",
			filters={"enabled": 1, "user_type": "System User"},
			pluck="name",
		)
		for user in users:
			frappe.clear_cache(user=user)

	return {"updated": int(updated), "assigned_roles": len(valid_roles)}
