from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint

from marina_custom_apps.permission_manager.api.modules import STANDARD_USERS, _module_catalogue


def execute(filters: dict[str, Any] | None = None):
	frappe.only_for("System Manager")
	filters = frappe._dict(filters or {})
	user_filters: dict[str, Any] = {
		"enabled": 1,
		"user_type": "System User",
		"name": ("not in", STANDARD_USERS),
	}
	if filters.user:
		if filters.user in STANDARD_USERS:
			return get_columns(), []
		user_filters["name"] = filters.user
	if filters.module_profile:
		user_filters["module_profile"] = filters.module_profile

	users = frappe.get_all(
		"User",
		filters=user_filters,
		fields=["name", "full_name", "module_profile"],
		order_by="full_name asc, name asc",
	)
	user_names = [user.name for user in users]
	blocked_by_user: dict[str, set[str]] = defaultdict(set)
	if user_names:
		for row in frappe.get_all(
			"Block Module",
			filters={"parenttype": "User", "parent": ("in", user_names)},
			fields=["parent", "module"],
		):
			blocked_by_user[row.parent].add(row.module)

	module_names = {module["module"] for module in _module_catalogue()}
	globally_blocked = set(
		frappe.get_all(
			"Block Module",
			filters={"parenttype": "User", "parent": "Administrator"},
			pluck="module",
		)
	) & module_names
	total_modules = len(module_names)
	data = []
	for user in users:
		blocked_modules = (blocked_by_user[user.name] & module_names) | globally_blocked
		blocked_count = len(blocked_modules)
		if cint(filters.only_with_blocks) and not blocked_count:
			continue
		available_modules = max(total_modules - blocked_count, 0)
		data.append(
			{
				"user": user.name,
				"full_name": user.full_name or user.name,
				"module_profile": user.module_profile,
				"active_modules": total_modules,
				"available_modules": available_modules,
				"blocked_modules": blocked_count,
				"availability_percent": (available_modules / total_modules * 100)
				if total_modules
				else 0,
			}
		)

	return get_columns(), data


def get_columns() -> list[dict[str, Any]]:
	return [
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": 220},
		{"fieldname": "full_name", "label": _("Full Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "module_profile",
			"label": _("Module Profile"),
			"fieldtype": "Link",
			"options": "Module Profile",
			"width": 180,
		},
		{"fieldname": "active_modules", "label": _("Active Modules"), "fieldtype": "Int", "width": 125},
		{
			"fieldname": "available_modules",
			"label": _("Available Modules"),
			"fieldtype": "Int",
			"width": 140,
		},
		{
			"fieldname": "blocked_modules",
			"label": _("Blocked Modules"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "availability_percent",
			"label": _("Availability %"),
			"fieldtype": "Percent",
			"precision": 1,
			"width": 130,
		},
	]
