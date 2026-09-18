from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.permissions import AUTOMATIC_ROLES, get_all_perms, setup_custom_perms
from frappe.utils import cint

RIGHTS = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"import",
	"export",
	"print",
	"email",
	"share",
)

BASIC_RIGHTS = ("select", "read", "write", "create", "submit", "cancel")
NOT_ALLOWED_IN_PERMISSION_MANAGER = ("DocType", "Patch Log", "Module Def", "Transaction Log")
MAX_BATCH_ROWS = 2000


def has_app_permission() -> bool:
	return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _active_doctype_filters() -> tuple[dict[str, Any], dict[str, Any]]:
	active_domains = frappe.get_active_domains()
	filters = {
		"istable": 0,
		"name": ("not in", NOT_ALLOWED_IN_PERMISSION_MANAGER),
	}
	or_filters = {
		"ifnull(restrict_to_domain, '')": "",
		"restrict_to_domain": ("in", active_domains),
	}
	return filters, or_filters


def _get_allowed_doctypes() -> list[frappe._dict]:
	filters, or_filters = _active_doctype_filters()
	return frappe.get_all(
		"DocType",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"module",
			"custom",
			"is_submittable",
			"issingle",
			"allow_import",
		],
		order_by="module asc, name asc",
	)


def _validate_role(role: str) -> None:
	if not role or not frappe.db.exists("Role", role):
		frappe.throw(_("Please select a valid Role."))

	if role == "Administrator":
		frappe.throw(_("Administrator permissions cannot be edited."))

	if frappe.session.user != "Administrator" and role in AUTOMATIC_ROLES:
		frappe.throw(_("Automatic role {0} can only be edited by Administrator.").format(frappe.bold(role)))

	if frappe.session.user != "Administrator":
		custom_user_type_role = frappe.db.exists("User Type", {"is_standard": 0, "role": role})
		if custom_user_type_role:
			frappe.throw(_("Role {0} is controlled by a custom User Type.").format(frappe.bold(role)))


def _permission_values(permission: Any) -> dict[str, int]:
	return {right: cint(permission.get(right)) for right in RIGHTS}


@frappe.whitelist()
def get_permission_matrix(role: str) -> dict[str, Any]:
	"""Return every eligible DocType and the effective rules for one role."""
	_only_system_manager()
	_validate_role(role)

	doctypes = _get_allowed_doctypes()
	module_apps = {
		row.name: (row.app_name or _("Custom"))
		for row in frappe.get_all("Module Def", fields=["name", "app_name"])
	}
	customized_doctypes = set(
		frappe.get_all("Custom DocPerm", distinct=True, pluck="parent")
	)

	permissions_by_doctype: dict[str, list[Any]] = defaultdict(list)
	for permission in get_all_perms(role):
		permissions_by_doctype[permission.parent].append(permission)

	rows: list[dict[str, Any]] = []
	for doctype in doctypes:
		app = module_apps.get(doctype.module) or _("Custom")
		permission_rows = permissions_by_doctype.get(doctype.name) or [None]

		for permission in sorted(
			permission_rows,
			key=lambda item: (cint(item.permlevel), cint(item.if_owner)) if item else (0, 0),
		):
			configured = permission is not None
			rows.append(
				{
					"doctype": doctype.name,
					"doctype_label": _(doctype.name),
					"module": doctype.module or _("Unassigned"),
					"module_label": _(doctype.module) if doctype.module else _("Unassigned"),
					"app": app,
					"permlevel": cint(permission.permlevel) if configured else 0,
					"if_owner": cint(permission.if_owner) if configured else 0,
					"configured": configured,
					"source": "custom" if doctype.name in customized_doctypes else ("standard" if configured else "none"),
					"is_submittable": cint(doctype.is_submittable),
					"issingle": cint(doctype.issingle),
					"allow_import": cint(doctype.allow_import),
					"rights": _permission_values(permission) if configured else {right: 0 for right in RIGHTS},
				}
			)

	rows.sort(
		key=lambda row: (
			str(row["app"]).casefold(),
			str(row["module_label"]).casefold(),
			str(row["doctype_label"]).casefold(),
			row["permlevel"],
			row["if_owner"],
		)
	)

	return {"role": role, "rights": RIGHTS, "rows": rows}


def _normalize_rights(meta: Any, permlevel: int, if_owner: int, rights: dict[str, Any]) -> dict[str, int]:
	normalized = {right: cint(rights.get(right)) for right in RIGHTS}

	if permlevel > 0:
		for right in RIGHTS:
			if right not in ("read", "write"):
				normalized[right] = 0

	if not meta.is_submittable:
		for right in ("submit", "cancel", "amend"):
			normalized[right] = 0

	if meta.issingle:
		for right in ("report", "import", "export"):
			normalized[right] = 0

	if not meta.allow_import:
		normalized["import"] = 0

	if if_owner:
		normalized["report"] = 0

	return normalized


def _upsert_permission_rule(
	doctype: str,
	role: str,
	permlevel: int,
	if_owner: int,
	rights: dict[str, int],
) -> None:
	setup_custom_perms(doctype)
	filters = {
		"parent": doctype,
		"role": role,
		"permlevel": permlevel,
		"if_owner": if_owner,
	}
	name = frappe.db.get_value("Custom DocPerm", filters)
	has_basic_permission = any(rights[right] for right in BASIC_RIGHTS)

	if not has_basic_permission:
		if name:
			frappe.db.delete("Custom DocPerm", {"name": name})
		return

	if name:
		permission = frappe.get_doc("Custom DocPerm", name)
	else:
		permission = frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": permlevel,
				"if_owner": if_owner,
			}
		)

	for right, value in rights.items():
		permission.set(right, value)

	if name:
		permission.db_update()
	else:
		permission.insert(ignore_permissions=True)


@frappe.whitelist()
def save_permission_matrix(role: str, changes: str | list[dict[str, Any]]) -> dict[str, Any]:
	"""Apply changed matrix rows as one validated database transaction."""
	_only_system_manager()
	_validate_role(role)

	parsed_changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
	if not isinstance(parsed_changes, list):
		frappe.throw(_("Permission changes must be a list."))
	if len(parsed_changes) > MAX_BATCH_ROWS:
		frappe.throw(_("A maximum of {0} rows can be changed in one save.").format(MAX_BATCH_ROWS))

	allowed_doctypes = {row.name for row in _get_allowed_doctypes()}
	affected_doctypes: set[str] = set()
	seen_keys: set[tuple[str, int, int]] = set()

	for change in parsed_changes:
		doctype = change.get("doctype")
		permlevel = cint(change.get("permlevel"))
		if_owner = cint(change.get("if_owner"))
		key = (doctype, permlevel, if_owner)

		if doctype not in allowed_doctypes:
			frappe.throw(_("Document Type {0} cannot be managed here.").format(frappe.bold(doctype)))
		if permlevel < 0 or permlevel > 9:
			frappe.throw(_("Permission Level must be between 0 and 9."))
		if key in seen_keys:
			frappe.throw(_("Duplicate permission change for {0} at level {1}.").format(doctype, permlevel))
		seen_keys.add(key)

		meta = frappe.get_meta(doctype)
		rights = _normalize_rights(meta, permlevel, if_owner, change.get("rights") or {})
		_upsert_permission_rule(doctype, role, permlevel, if_owner, rights)
		affected_doctypes.add(doctype)

	for doctype in affected_doctypes:
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			frappe.throw(
				_("Cannot remove the final permission rule from {0}.").format(frappe.bold(doctype))
			)
		validate_permissions_for_doctype(doctype)

	return {
		"updated_rows": len(parsed_changes),
		"affected_doctypes": len(affected_doctypes),
	}
