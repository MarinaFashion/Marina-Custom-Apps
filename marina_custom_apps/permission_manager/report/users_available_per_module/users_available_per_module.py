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
	modules = _module_catalogue()
	if filters.module:
		modules = [module for module in modules if module["module"] == filters.module]

	users = frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"user_type": "System User",
			"name": ("not in", STANDARD_USERS),
		},
		pluck="name",
	)
	blocked_by_module: dict[str, set[str]] = defaultdict(set)
	if users:
		for row in frappe.get_all(
			"Block Module",
			filters={"parenttype": "User", "parent": ("in", users)},
			fields=["parent", "module"],
		):
			blocked_by_module[row.module].add(row.parent)

	globally_blocked = set(
		frappe.get_all(
			"Block Module",
			filters={"parenttype": "User", "parent": "Administrator"},
			pluck="module",
		)
	)
	active_users = len(users)
	data = []
	for module in modules:
		module_name = module["module"]
		is_global = module_name in globally_blocked
		blocked_users = active_users if is_global else len(blocked_by_module[module_name])
		if cint(filters.only_with_blocks) and not blocked_users:
			continue
		available_users = max(active_users - blocked_users, 0)
		data.append(
			{
				"app": module["app"],
				"module": module_name,
				"active_users": active_users,
				"available_users": available_users,
				"blocked_users": blocked_users,
				"availability_percent": (available_users / active_users * 100) if active_users else 0,
				"globally_blocked": is_global,
			}
		)

	return get_columns(), data


def get_columns() -> list[dict[str, Any]]:
	return [
		{"fieldname": "app", "label": _("Application"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "module",
			"label": _("Module"),
			"fieldtype": "Link",
			"options": "Module Def",
			"width": 220,
		},
		{"fieldname": "active_users", "label": _("Active Users"), "fieldtype": "Int", "width": 120},
		{
			"fieldname": "available_users",
			"label": _("Available Users"),
			"fieldtype": "Int",
			"width": 135,
		},
		{"fieldname": "blocked_users", "label": _("Blocked Users"), "fieldtype": "Int", "width": 125},
		{
			"fieldname": "availability_percent",
			"label": _("Availability %"),
			"fieldtype": "Percent",
			"precision": 1,
			"width": 130,
		},
		{
			"fieldname": "globally_blocked",
			"label": _("Globally Blocked"),
			"fieldtype": "Check",
			"width": 130,
		},
	]
