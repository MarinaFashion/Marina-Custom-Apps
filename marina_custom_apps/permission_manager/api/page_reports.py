from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.permissions import AUTOMATIC_ROLES
from frappe.utils import cint

RESOURCE_TYPES = ("Page", "Report")
MAX_BATCH_ROWS = 2000


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _validate_role(role: str) -> None:
	if not role or not frappe.db.exists("Role", {"name": role, "disabled": 0}):
		frappe.throw(_("Please select a valid enabled Role."))
	if role in AUTOMATIC_ROLES:
		frappe.throw(_("Automatic roles cannot be managed here."))


def _validate_resource_type(resource_type: str) -> None:
	if resource_type not in RESOURCE_TYPES:
		frappe.throw(_("Resource Type must be Page or Report."))


def _module_apps() -> dict[str, str]:
	return {
		row.module_name: (row.app_name or _("Custom"))
		for row in frappe.get_all("Module Def", fields=["module_name", "app_name"])
	}


def _get_resources(resource_type: str) -> list[Any]:
	if resource_type == "Page":
		return frappe.get_all(
			"Page",
			filters={"system_page": 0},
			fields=["name", "title", "module"],
			order_by="module asc, title asc, name asc",
		)

	return frappe.get_all(
		"Report",
		filters={"disabled": 0},
		fields=["name", "report_name", "module", "report_type", "ref_doctype"],
		order_by="module asc, report_name asc, name asc",
	)


def _roles_by_parent(parenttype: str, parents: list[str]) -> dict[str, set[str]]:
	roles: dict[str, set[str]] = defaultdict(set)
	if not parents:
		return roles

	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": parenttype, "parent": ("in", parents)},
		fields=["parent", "role"],
	):
		roles[row.parent].add(row.role)
	return roles


def _custom_role_documents(resource_type: str, resources: list[str]) -> dict[str, Any]:
	fieldname = resource_type.lower()
	return {
		row.get(fieldname): row
		for row in frappe.get_all(
			"Custom Role",
			filters={fieldname: ("in", resources)},
			fields=["name", fieldname],
		)
		if row.get(fieldname)
	}


@frappe.whitelist()
def get_page_report_matrix(role: str, resource_type: str) -> dict[str, Any]:
	"""Return effective Page or Report access for one role."""
	_only_system_manager()
	_validate_role(role)
	_validate_resource_type(resource_type)

	resources = _get_resources(resource_type)
	resource_names = [resource.name for resource in resources]
	standard_roles = _roles_by_parent(resource_type, resource_names)
	custom_docs = _custom_role_documents(resource_type, resource_names)
	custom_roles = _roles_by_parent("Custom Role", [doc.name for doc in custom_docs.values()])
	module_apps = _module_apps()

	rows = []
	for resource in resources:
		custom_doc = custom_docs.get(resource.name)
		standard = standard_roles[resource.name]
		if custom_doc:
			custom = custom_roles[custom_doc.name]
			open_to_all = bool(custom.intersection(AUTOMATIC_ROLES))
			allowed = open_to_all or role in custom
			source = "custom"
		else:
			open_to_all = not standard or bool(standard.intersection(AUTOMATIC_ROLES))
			allowed = open_to_all or role in standard
			source = "open" if open_to_all else "standard"

		label = resource.title if resource_type == "Page" else resource.report_name
		rows.append(
			{
				"resource": resource.name,
				"label": label or resource.name,
				"resource_type": resource_type,
				"module": resource.module or _("Unassigned"),
				"app": module_apps.get(resource.module) or _("Custom"),
				"allowed": allowed,
				"source": source,
				"open_to_all": open_to_all,
				"report_type": resource.get("report_type"),
				"ref_doctype": resource.get("ref_doctype"),
			}
		)

	rows.sort(
		key=lambda row: (
			str(row["app"]).casefold(),
			str(row["module"]).casefold(),
			str(row["label"]).casefold(),
		)
	)
	return {"role": role, "resource_type": resource_type, "rows": rows}


def _save_resource_role(resource_type: str, resource: str, role: str, allowed: bool) -> bool:
	fieldname = resource_type.lower()
	custom_name = frappe.db.get_value("Custom Role", {fieldname: resource}, "name")
	standard_roles = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": resource_type, "parent": resource},
			pluck="role",
		)
	)

	standard_is_open = not standard_roles or bool(standard_roles.intersection(AUTOMATIC_ROLES))
	if not custom_name and standard_is_open:
		if allowed:
			return False
		frappe.throw(
			_("{0} {1} is open to all roles and cannot exclude only one role.").format(
				resource_type, frappe.bold(resource)
			)
		)

	if custom_name:
		custom_doc = frappe.get_doc("Custom Role", custom_name)
		roles = {row.role for row in custom_doc.roles}
		if roles.intersection(AUTOMATIC_ROLES):
			frappe.throw(
				_("{0} {1} is open to all roles and cannot exclude only one role.").format(
					resource_type, frappe.bold(resource)
				)
			)
	else:
		custom_doc = frappe.get_doc(
			{
				"doctype": "Custom Role",
				fieldname: resource,
				"ref_doctype": frappe.db.get_value("Report", resource, "ref_doctype")
				if resource_type == "Report"
				else None,
			}
		)
		roles = set(standard_roles)

	before = set(roles)
	if allowed:
		roles.add(role)
	else:
		roles.discard(role)
	if roles == before:
		return False

	# When a resource has standard restrictions, matching them exactly means the override is
	# no longer needed. An empty standard role list means open-to-all, so an empty Custom Role
	# must be retained to represent blocked-for-all. Automatic-role resources are protected
	# earlier because their access also applies broadly to Desk users.
	if custom_name and standard_roles and roles == standard_roles:
		frappe.delete_doc("Custom Role", custom_name, ignore_permissions=True)
		return True

	custom_doc.set("roles", [])
	for assigned_role in sorted(roles):
		custom_doc.append("roles", {"role": assigned_role})
	if custom_name:
		custom_doc.save(ignore_permissions=True)
	else:
		custom_doc.insert(ignore_permissions=True)
	return True


def _clear_role_user_caches(role: str) -> None:
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": role},
		pluck="parent",
	)
	for user in set(users):
		frappe.clear_cache(user=user)


def _replace_open_resource_roles(
	resource_type: str,
	resources: list[str],
	roles: set[str],
) -> dict[str, int]:
	"""Replace effective open access with one explicit role list.

	Resources that are no longer open when the request is processed are skipped. This keeps
	bulk conversion safe when another administrator changes permissions after the matrix loads.
	"""
	standard_roles = _roles_by_parent(resource_type, resources)
	custom_docs = _custom_role_documents(resource_type, resources)
	custom_roles = _roles_by_parent(
		"Custom Role",
		[doc.name for doc in custom_docs.values()],
	)
	fieldname = resource_type.lower()
	updated_rows = 0
	skipped_rows = 0

	for resource in resources:
		custom_doc_row = custom_docs.get(resource)
		if custom_doc_row:
			is_open = bool(custom_roles[custom_doc_row.name].intersection(AUTOMATIC_ROLES))
		else:
			standard = standard_roles[resource]
			is_open = not standard or bool(standard.intersection(AUTOMATIC_ROLES))

		if not is_open:
			skipped_rows += 1
			continue

		if custom_doc_row:
			custom_doc = frappe.get_doc("Custom Role", custom_doc_row.name)
		else:
			custom_doc = frappe.get_doc(
				{
					"doctype": "Custom Role",
					fieldname: resource,
					"ref_doctype": frappe.db.get_value("Report", resource, "ref_doctype")
					if resource_type == "Report"
					else None,
				}
			)

		custom_doc.set("roles", [])
		for role in sorted(roles):
			custom_doc.append("roles", {"role": role})
		if custom_doc_row:
			custom_doc.save(ignore_permissions=True)
		else:
			custom_doc.insert(ignore_permissions=True)
		updated_rows += 1

	return {"updated_rows": updated_rows, "skipped_rows": skipped_rows}


@frappe.whitelist()
def restrict_open_resources(
	resource_type: str,
	resources: str | list[str],
	roles: str | list[str],
) -> dict[str, int]:
	"""Convert open Pages or Reports to an exact, explicitly selected role list."""
	_only_system_manager()
	_validate_resource_type(resource_type)

	parsed_resources = frappe.parse_json(resources) if isinstance(resources, str) else resources
	parsed_roles = frappe.parse_json(roles) if isinstance(roles, str) else roles
	if not isinstance(parsed_resources, list) or not all(
		isinstance(resource, str) and resource for resource in parsed_resources
	):
		frappe.throw(_("Selected Pages or Reports must be a list."))
	if not isinstance(parsed_roles, list) or not all(
		isinstance(role, str) and role for role in parsed_roles
	):
		frappe.throw(_("Allowed Roles must be a list."))

	parsed_resources = list(dict.fromkeys(parsed_resources))
	parsed_roles = list(dict.fromkeys(parsed_roles))
	if not parsed_resources:
		frappe.throw(_("Select at least one open Page or Report."))
	if len(parsed_resources) > MAX_BATCH_ROWS:
		frappe.throw(_("A maximum of {0} rows can be restricted in one action.").format(MAX_BATCH_ROWS))
	if not parsed_roles:
		frappe.throw(_("Select at least one Role that should retain access."))
	for role in parsed_roles:
		_validate_role(role)

	allowed_resources = {resource.name for resource in _get_resources(resource_type)}
	if not set(parsed_resources).issubset(allowed_resources):
		frappe.throw(_("One or more Pages or Reports cannot be managed here."))

	result = _replace_open_resource_roles(resource_type, parsed_resources, set(parsed_roles))
	if result["updated_rows"]:
		# Open access affects every Desk user, so invalidate permission metadata globally rather
		# than clearing only the newly selected roles.
		frappe.clear_cache()
	return result


@frappe.whitelist()
def save_page_report_matrix(
	role: str,
	resource_type: str,
	changes: str | list[dict[str, Any]],
) -> dict[str, int]:
	"""Apply Page or Report role changes in one validated transaction."""
	_only_system_manager()
	_validate_role(role)
	_validate_resource_type(resource_type)

	parsed_changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
	if not isinstance(parsed_changes, list):
		frappe.throw(_("Page and Report permission changes must be a list."))
	if len(parsed_changes) > MAX_BATCH_ROWS:
		frappe.throw(_("A maximum of {0} rows can be changed in one save.").format(MAX_BATCH_ROWS))
	if any(not isinstance(change, dict) or not change.get("resource") for change in parsed_changes):
		frappe.throw(_("Every permission change must include a Page or Report."))

	resources = [change["resource"] for change in parsed_changes]
	if len(resources) != len(set(resources)):
		frappe.throw(_("Each Page or Report can appear only once in the change list."))

	allowed_resources = {resource.name for resource in _get_resources(resource_type)}
	if not set(resources).issubset(allowed_resources):
		frappe.throw(_("One or more Pages or Reports cannot be managed here."))

	updated_rows = 0
	for change in parsed_changes:
		if _save_resource_role(
			resource_type,
			change["resource"],
			role,
			bool(cint(change.get("allowed"))),
		):
			updated_rows += 1

	if updated_rows:
		_clear_role_user_caches(role)
	return {"updated_rows": updated_rows}
