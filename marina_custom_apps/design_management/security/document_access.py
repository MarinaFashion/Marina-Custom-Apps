"""Role-based document assignment and staff selection; no legacy user lists."""
import frappe
from marina_custom_apps.design_management.security.participants import participant_ids, is_participant
from marina_custom_apps.design_management.security.organization import owner_roles
from marina_custom_apps.design_management.security.role_access import can_doctype


def configured_users(table):
    field={"merchandisers":"assigned_merchandiser",
           "designers":"designer",
           "fitting_team":"technical_fitting_responsible"}.get(table)
    if not field:
        return set()
    roles=sorted(owner_roles(field))
    if not roles:
        return set()
    return participant_ids(frappe.get_all("Design Module User Role", filters={
        "parent":"Design Management Settings",
        "parenttype":"Design Management Settings",
        "parentfield":"module_user_roles",
        "active":1,"module_role":["in",roles],
    }, pluck="user", limit_page_length=1000))


def eligible_user(user, table):
    return bool(user and user in configured_users(table) and is_participant(user))


def can_manage_documents(user):
    # None means module RBAC is disabled; native Frappe permissions still apply.
    # Explicit module denials remain enforced when RBAC is enabled.
    return can_doctype("Design Document", "write", user) is not False


def can_assign_design(user, design_name):
    # Managers may not assign evidence to designs they cannot read.
    return bool(frappe.has_permission("Design Code","read",
                                      doc=design_name,user=user))
