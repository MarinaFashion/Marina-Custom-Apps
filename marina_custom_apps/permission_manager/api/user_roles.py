from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.core.doctype.user.user import get_all_roles
from frappe.utils import cint

STANDARD_USERS = ("Administrator", "Guest")
MAX_BATCH_USERS = 500


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _roles() -> list[str]:
	"""Use Frappe's active, domain-aware role catalogue."""
	return sorted(set(get_all_roles()), key=str.casefold)


def _validate_role(role: str) -> None:
	if not role or role not in _roles():
		frappe.throw(_("Please select an active role available in the current domain."))


def _desk_users() -> list[Any]:
	return frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ("not in", STANDARD_USERS),
		},
		fields=["name", "full_name", "role_profile_name"],
		order_by="full_name asc, name asc",
		limit_page_length=0,
	)


def _user_doc(user: str) -> Any:
	if not user or user in STANDARD_USERS:
		frappe.throw(_("Please select an active Desk user."))
	doc = frappe.get_doc("User", user)
	if not cint(doc.enabled) or doc.user_type != "System User":
		frappe.throw(_("Please select an active Desk user."))
	return doc


def _assigned_roles(doc: Any) -> set[str]:
	return {row.role for row in doc.roles if row.role}


def _assert_editable(doc: Any) -> None:
	if doc.role_profile_name:
		frappe.throw(
			_("User {0} uses Role Profile {1}. Edit the Role Profile or the User record first.").format(
				frappe.bold(doc.name), frappe.bold(doc.role_profile_name)
			)
		)


def _assert_self_access(doc: Any, requested_roles: set[str]) -> None:
	if doc.name == frappe.session.user and "System Manager" not in requested_roles:
		frappe.throw(_("You cannot remove your own System Manager role from this page."))


@frappe.whitelist()
def get_roles_catalogue() -> dict[str, Any]:
	_only_system_manager()
	return {"roles": _roles()}


@frappe.whitelist()
def get_role_users(role: str) -> dict[str, Any]:
	_only_system_manager()
	_validate_role(role)
	users = _desk_users()
	names = [user.name for user in users]
	assigned = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "parent": ("in", names or [""]), "role": role},
			pluck="parent",
			limit_page_length=0,
		)
	)
	return {
		"role": role,
		"users": [
			{
				"user": user.name,
				"full_name": user.full_name or user.name,
				"role_profile": user.role_profile_name or "",
				"assigned": user.name in assigned,
				"editable": not bool(user.role_profile_name)
				and not (user.name == frappe.session.user and role == "System Manager"),
			}
			for user in users
		],
	}


@frappe.whitelist()
def get_user_roles(user: str) -> dict[str, Any]:
	_only_system_manager()
	doc = _user_doc(user)
	return {
		"user": doc.name,
		"full_name": doc.full_name or doc.name,
		"role_profile": doc.role_profile_name or "",
		"roles": [
			{
				"role": role,
				"assigned": role in _assigned_roles(doc),
				"editable": not bool(doc.role_profile_name)
				and not (doc.name == frappe.session.user and role == "System Manager"),
			}
			for role in _roles()
		],
	}


@frappe.whitelist()
def get_role_users_list() -> dict[str, Any]:
	_only_system_manager()
	return {
		"users": [
			{"user": row.name, "full_name": row.full_name or row.name}
			for row in _desk_users()
		]
	}


@frappe.whitelist()
def save_role_users(role: str, changes: str | list[dict[str, Any]]) -> dict[str, int]:
	_only_system_manager()
	_validate_role(role)
	items = frappe.parse_json(changes) if isinstance(changes, str) else changes
	if not isinstance(items, list) or len(items) > MAX_BATCH_USERS:
		frappe.throw(_("Provide at most {0} user changes.").format(MAX_BATCH_USERS))
	if any(not isinstance(item, dict) or not isinstance(item.get("user"), str)
		or item.get("assigned") not in (0, 1, False, True)
		or item.get("expected") not in (0, 1, False, True) for item in items):
		frappe.throw(_("Every change needs a user, an assignment and its original value."))
	names = [item["user"] for item in items]
	if len(names) != len(set(names)):
		frappe.throw(_("Each user may appear only once."))

	prepared = []
	for item in items:
		doc = _user_doc(item["user"])
		_assert_editable(doc)
		current = role in _assigned_roles(doc)
		if current != bool(cint(item["expected"])):
			frappe.throw(_("Role assignments for {0} changed since loading. Refresh and try again.").format(frappe.bold(doc.name)))
		want = bool(cint(item["assigned"]))
		if current == want:
			continue
		if doc.name == frappe.session.user and role == "System Manager" and not want:
			frappe.throw(_("You cannot remove your own System Manager role from this page."))
		prepared.append((doc, want))

	for doc, want in prepared:
		if want:
			doc.append("roles", {"role": role})
		else:
			doc.roles = [row for row in doc.roles if row.role != role]
		doc.save(ignore_permissions=True)
	return {"updated_users": len(prepared)}


@frappe.whitelist()
def save_user_roles(user: str, roles: str | list[str], expected: str | list[str]) -> dict[str, int]:
	_only_system_manager()
	doc = _user_doc(user)
	_assert_editable(doc)
	selected = frappe.parse_json(roles) if isinstance(roles, str) else roles
	prior = frappe.parse_json(expected) if isinstance(expected, str) else expected
	available = set(_roles())
	if any(not isinstance(values, list) or any(not isinstance(role, str) or role not in available for role in values)
		or len(values) != len(set(values)) for values in (selected, prior)):
		frappe.throw(_("Select only active roles from the catalogue."))
	current = _assigned_roles(doc)
	if current & available != set(prior):
		frappe.throw(_("This user's role assignments changed since loading. Refresh and try again."))
	target = (current - available) | set(selected)
	_assert_self_access(doc, target)
	if target == current:
		return {"updated_users": 0}
	doc.roles = [row for row in doc.roles if row.role in target]
	for role in sorted(target - current):
		doc.append("roles", {"role": role})
	doc.save(ignore_permissions=True)
	return {"updated_users": 1}
