"""Small role-backed user selectors for the clean Design Code form."""
import frappe
from marina_custom_apps.design_management.security.organization import (
    OWNER_GROUPS, owner_roles, user_roles,
)
from marina_custom_apps.design_management.security.role_access import enabled
from marina_custom_apps.design_management.security.participants import participant_ids


@frappe.whitelist()
def current_user_is_merchandiser():
    user=frappe.session.user
    if user in ("Guest",None,"") or not enabled():
        return False
    return bool(user_roles(user) & owner_roles("assigned_merchandiser"))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_responsible_users(doctype, txt, searchfield, start, page_len, filters):
    if isinstance(filters,str):
        filters=frappe.parse_json(filters)
    filters=filters or {}
    field=filters.get("owner_field")
    if field not in OWNER_GROUPS:
        return []
    if not (frappe.has_permission("Design Code","read")
            or frappe.has_permission("Mood Board","read")):
        return []
    roles=sorted(owner_roles(field))
    if not roles:
        return []
    assignments=frappe.get_all("Design Module User Role",filters={
        "parent":"Design Management Settings",
        "parenttype":"Design Management Settings",
        "parentfield":"module_user_roles",
        "active":1,"module_role":["in",roles],
    },fields=["user"],limit_page_length=1000)
    ids=sorted(participant_ids(x.user for x in assignments))
    if not ids:
        return []
    users=frappe.get_all("User",filters={
        "name":["in",ids],"enabled":1,"user_type":"System User",
    },fields=["name","username"],limit_page_length=len(ids))
    query=(txt or "").casefold().strip()
    candidates=sorted((x.name,x.username.strip()) for x in users
        if x.username and (query in x.username.casefold()
                           or query in x.name.casefold()))
    begin=max(0,int(start))
    return candidates[begin:begin+min(50,max(1,int(page_len)))]
