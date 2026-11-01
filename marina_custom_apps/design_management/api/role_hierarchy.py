"""Read-only reporting hierarchy for the Design Module Role tree page.

Uses the existing Reports To Role relationship, without nested-set columns,
schema conversion, or any mutation of role/permission records.
"""
import frappe


@frappe.whitelist()
def get_role_hierarchy():
    """Return authorized role metadata in one bounded list query.

    The tree never exposes linked User IDs, user assignments or emails.
    Mutations must go through the existing Design Module Role controller.
    """
    if frappe.session.user == "Guest" or not frappe.has_permission(
        "Design Module Role", "read"
    ):
        frappe.throw("Not permitted to view the role hierarchy", frappe.PermissionError)

    rows = frappe.get_list(
        "Design Module Role",
        fields=[
            "name", "role_name", "reports_to_role", "role_type",
            "scope", "responsibility_group", "enabled",
        ],
        order_by="role_name asc",
        limit_page_length=501,
    )
    if len(rows) > 500:
        frappe.throw("Role hierarchy exceeds the supported 500-role limit")

    can_manage = (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles(frappe.session.user)
    )
    return {"roles": rows, "can_manage": can_manage}
