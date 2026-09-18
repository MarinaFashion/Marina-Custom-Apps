from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.config import get_modules_from_all_apps
from frappe.utils import cint, now

MAX_BATCH_USERS = 500
STANDARD_USERS = ("Administrator", "Guest")


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _module_catalogue() -> list[dict[str, str]]:
	modules: dict[str, str] = {}
	for module in get_modules_from_all_apps():
		module_name = module.get("module_name")
		if module_name:
			modules[module_name] = module.get("app") or _("Custom")

	return [
		{"module": module_name, "app": app}
		for module_name, app in sorted(
			modules.items(), key=lambda item: (str(item[1]).casefold(), str(item[0]).casefold())
		)
	]


def _validate_module(module: str) -> dict[str, str]:
	match = next((item for item in _module_catalogue() if item["module"] == module), None)
	if not match:
		frappe.throw(_("Please select a valid module."))
	return match


def _blocked_modules_for_users(users: list[str], module: str) -> set[str]:
	if not users:
		return set()

	return set(
		frappe.get_all(
			"Block Module",
			filters={
				"parenttype": "User",
				"parent": ("in", users),
				"module": module,
			},
			pluck="parent",
		)
	)


def _is_globally_blocked(module: str) -> bool:
	return bool(
		frappe.db.exists(
			"Block Module",
			{
				"parenttype": "User",
				"parent": "Administrator",
				"module": module,
			},
		)
	)


@frappe.whitelist()
def get_modules() -> dict[str, Any]:
	"""Return installed modules grouped by their owning application."""
	_only_system_manager()
	return {"modules": _module_catalogue()}


@frappe.whitelist()
def get_module_users(module: str) -> dict[str, Any]:
	"""Return enabled Desk users and whether the selected module is available to each user."""
	_only_system_manager()
	module_info = _validate_module(module)

	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ("not in", STANDARD_USERS),
		},
		fields=["name", "full_name", "module_profile"],
		order_by="full_name asc, name asc",
	)
	user_names = [user.name for user in users]
	blocked_users = _blocked_modules_for_users(user_names, module)
	globally_blocked = _is_globally_blocked(module)

	return {
		"module": module,
		"app": module_info["app"],
		"globally_blocked": globally_blocked,
		"users": [
			{
				"user": user.name,
				"full_name": user.full_name or user.name,
				"module_profile": user.module_profile,
				"available": not globally_blocked and user.name not in blocked_users,
			}
			for user in users
		],
	}


def _set_module_availability(user: str, module: str, available: bool) -> bool:
	"""Update one module without changing the user's other module selections.

	A changed user controlled by a shared Module Profile becomes individually managed. The
	existing Block Module rows already mirror the profile, so the user's other module settings
	remain unchanged.
	"""
	filters = {
		"parenttype": "User",
		"parent": user,
		"module": module,
	}
	existing = frappe.db.exists("Block Module", filters)

	if available and existing:
		frappe.db.delete("Block Module", filters)
	elif not available and not existing:
		frappe.get_doc(
			{
				"doctype": "Block Module",
				"parent": user,
				"parenttype": "User",
				"parentfield": "block_modules",
				"module": module,
			}
		).insert(ignore_permissions=True)
	else:
		return False

	frappe.db.set_value(
		"User",
		user,
		{
			"modified": now(),
			"modified_by": frappe.session.user,
		},
		update_modified=False,
	)
	frappe.clear_cache(user=user)
	return True


@frappe.whitelist()
def save_module_users(module: str, changes: str | list[dict[str, Any]]) -> dict[str, Any]:
	"""Apply availability changes for one module as a single database transaction."""
	_only_system_manager()
	_validate_module(module)

	if _is_globally_blocked(module):
		frappe.throw(
			_("Module {0} is blocked globally through the Administrator user.").format(
				frappe.bold(module)
			)
		)

	parsed_changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
	if not isinstance(parsed_changes, list):
		frappe.throw(_("Module assignment changes must be a list."))
	if len(parsed_changes) > MAX_BATCH_USERS:
		frappe.throw(_("A maximum of {0} users can be changed in one save.").format(MAX_BATCH_USERS))

	if any(not isinstance(change, dict) or not change.get("user") for change in parsed_changes):
		frappe.throw(_("Every module assignment change must include a user."))

	requested_users = [change["user"] for change in parsed_changes]
	if len(requested_users) != len(set(requested_users)):
		frappe.throw(_("Each user can appear only once in the change list."))
	if any(user in STANDARD_USERS for user in requested_users):
		frappe.throw(_("Standard users cannot be managed here."))

	valid_users = {
		user.name: user.module_profile
		for user in frappe.get_all(
			"User",
			filters={
				"enabled": 1,
				"user_type": "System User",
				"name": ("in", requested_users or [""]),
			},
			fields=["name", "module_profile"],
		)
	}

	if set(requested_users) != set(valid_users):
		frappe.throw(_("One or more selected users are disabled or cannot be managed here."))

	updated_users = 0
	detached_users = 0
	for change in parsed_changes:
		user = change["user"]
		available = bool(cint(change.get("available")))
		currently_blocked = bool(
			frappe.db.exists(
				"Block Module",
				{"parenttype": "User", "parent": user, "module": module},
			)
		)
		if available == (not currently_blocked):
			continue

		if valid_users[user]:
			frappe.db.set_value("User", user, "module_profile", None)
			valid_users[user] = None
			detached_users += 1

		if _set_module_availability(user, module, available):
			updated_users += 1

	return {
		"updated_users": updated_users,
		"detached_users": detached_users,
	}
