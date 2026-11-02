"""Configurable Marina Design organization; initial roles are seeds, not limits.

Authority uses server-configured module roles. Reporting grants assignment reach
only when the actor also has the relevant workflow action; it never grants QC or
Technical Fitting approval on its own. Record access is always role-scoped.
"""
import frappe

# Approved initial Module Role hierarchy; administrators assign actual employees.
REPORTS_TO = {
    "Administrator": None,
    "Head Of Design": "Administrator",
    "Designer": "Head Of Design",
    "Technical Fitting Manager": "Administrator",
    "Technical Fitting Officer": "Technical Fitting Manager",
    "China Office Manager": "Administrator",
    "Head Of Merchandisers": "China Office Manager",
    "Merchandiser": "Head Of Merchandisers",
    "QC Manager": "China Office Manager",
    "QC Officer": "QC Manager",
    "Shipping Coordinator": "China Office Manager",
    "Buying Manager": "Administrator",
    "Buying Officer": "Buying Manager",
}
HEADS = frozenset({
    "Administrator", "Head Of Design", "Technical Fitting Manager",
    "China Office Manager", "Head Of Merchandisers", "QC Manager", "Buying Manager",
})
DEFAULT_GROUPS = {
    "Administrator": "Other",
    "Head Of Design": "Design", "Designer": "Design",
    "Technical Fitting Manager": "Technical Fitting",
    "Technical Fitting Officer": "Technical Fitting",
    "China Office Manager": "Other",
    "Head Of Merchandisers": "Merchandising",
    "Merchandiser": "Merchandising",
    "QC Manager": "QC", "QC Officer": "QC",
    "Shipping Coordinator": "Shipping",
    "Buying Manager": "Buying", "Buying Officer": "Buying",
}
RESPONSIBILITY_GROUPS = frozenset({
    "Design", "Merchandising", "Technical Fitting", "QC",
    "Shipping", "Buying", "Other",
})
OWNER_GROUPS = {
    "designer": "Design",
    "assigned_merchandiser": "Merchandising",
    "technical_fitting_responsible": "Technical Fitting",
}

def clear_role_cache():
    for name in ("_marina_org_catalog", "_marina_org_user_roles",
                 "_marina_design_rbac", "_marina_default_assignees",
                 "_marina_participant_checks"):
        if hasattr(frappe.local, name):
            delattr(frappe.local, name)


def role_catalog():
    """One bounded master query per request. Only enabled module roles count."""
    cached = getattr(frappe.local, "_marina_org_catalog", None)
    if cached is not None:
        return cached
    roles = frappe.get_all("Design Module Role", filters={"enabled": 1},
        fields=["name", "reports_to_role", "role_type", "scope",
                "responsibility_group"], limit_page_length=501)
    if len(roles) > 500:
        frappe.throw("Too many module roles for permission evaluation")
    catalog = {r.name: r for r in roles}
    frappe.local._marina_org_catalog = catalog
    return catalog


def descendants(role):
    catalog = role_catalog()
    if role not in catalog:
        return set()
    result, queue = set(), [role]
    while queue:
        current = queue.pop()
        if current in result:
            continue
        result.add(current)
        queue.extend(child for child, row in catalog.items()
                     if row.reports_to_role == current and child not in result)
    return result


def user_roles(user):
    if not user:
        return set()
    # Module role membership is independent of RBAC enforcement.
    # RBAC toggles authorization checks, not active staff assignments.
    cache = getattr(frappe.local, "_marina_org_user_roles", None)
    if cache is None:
        cache = {}
        frappe.local._marina_org_user_roles = cache
    if user not in cache:
        assigned = frappe.get_all("Design Module User Role",
            filters={"parent": "Design Management Settings",
                     "parenttype": "Design Management Settings",
                     "parentfield": "module_user_roles",
                     "active": 1, "user": user},
            pluck="module_role", limit_page_length=100)
        cache[user] = set(assigned) & set(role_catalog())
    return cache[user]


def manager_roles(user):
    catalog = role_catalog()
    return {role for role in user_roles(user)
            if catalog[role].role_type == "Manager"}


def is_head(user):
    return bool(manager_roles(user))


def has_overall_visibility(user):
    catalog = role_catalog()
    return any(catalog[role].scope == "All" for role in user_roles(user))


def owner_roles(field):
    group = OWNER_GROUPS.get(field)
    return roles_for_group(group) if group else set()


def roles_for_group(group):
    if not group:
        return set()
    return {role for role, data in role_catalog().items()
            if data.responsibility_group == group}


def can_manage_role(actor, target_role):
    from marina_custom_apps.design_management.security.role_access import can_action
    if not (can_action("Assign Team Tasks", actor)
            or can_action("Reassign Team Tasks", actor)):
        return False
    return any(target_role in descendants(role) for role in manager_roles(actor))


def is_eligible_for_owner(user, field):
    if field not in OWNER_GROUPS or not user:
        return False
    from marina_custom_apps.design_management.security.participants import is_participant
    return bool(user_roles(user) & owner_roles(field) and is_participant(user))


def can_assign_owner(actor, field, target_user):
    if field not in OWNER_GROUPS:
        return False
    from marina_custom_apps.design_management.security.participants import is_participant
    if not is_participant(target_user):
        return False
    target_roles = user_roles(target_user) & owner_roles(field)
    return bool(target_roles and any(can_manage_role(actor, role)
                                    for role in target_roles))


def assigned_to_design(user, design):
    if user in (design.designer, design.assigned_merchandiser,
                design.get("technical_fitting_responsible")):
        return True
    if not design.name:
        return False
    if frappe.db.exists("Design Team Assignment", {
        "parent": design.name, "parenttype": "Design Code",
        "parentfield": "r22_team_assignments", "active": 1, "user": user,
    }):
        return True
    return bool(frappe.db.exists("Design Milestone Execution", {
        "design_code": design.name,
        "status": ["!=", "Completed"],
        "current_custodian": user,
    }))


def assigned_scope_sql(user, table="tabDesign Code"):
    escaped = frappe.db.escape(user)
    return (
        "(`" + table + "`.designer=" + escaped +
        " OR `" + table + "`.assigned_merchandiser=" + escaped +
        " OR `" + table + "`.technical_fitting_responsible=" + escaped +
        " OR EXISTS (SELECT 1 FROM `tabDesign Team Assignment` ta "
        "WHERE ta.parent=`" + table + "`.name AND ta.parenttype='Design Code' "
        "AND ta.parentfield='r22_team_assignments' AND ta.active=1 "
        "AND ta.user=" + escaped + ")"
        " OR EXISTS (SELECT 1 FROM `tabDesign Milestone Execution` x "
        "WHERE x.design_code=`" + table + "`.name "
        "AND x.status!='Completed' AND x.current_custodian=" + escaped + "))"
    )


def eligible_team_users(actor, target_role=None):
    from marina_custom_apps.design_management.security.role_access import can_action
    if not (can_action("Assign Team Tasks", actor)
            or can_action("Reassign Team Tasks", actor)):
        return []
    permitted = set()
    for role in manager_roles(actor):
        permitted.update(descendants(role))
    if target_role:
        permitted &= {target_role}
    if not permitted:
        return []
    assignments = frappe.get_all("Design Module User Role",
        filters={"parent": "Design Management Settings",
                 "parentfield": "module_user_roles", "active": 1,
                 "module_role": ["in", sorted(permitted)]},
        fields=["user", "module_role"], limit_page_length=1000)
    from marina_custom_apps.design_management.security.participants import participant_ids
    users = sorted(participant_ids(r.user for r in assignments))
    if not users:
        return []
    titles = {r.name: (r.username or "").strip()
              for r in frappe.get_all("User",
                  filters={"name": ["in", users], "enabled": 1,
                           "user_type": "System User"},
                  fields=["name", "username"], limit_page_length=len(users))}
    return [{"value": r.user, "label": titles[r.user], "role": r.module_role}
            for r in assignments if titles.get(r.user)]


def can_reassign_task(actor, prior_user, new_user):
    from marina_custom_apps.design_management.security.role_access import can_action
    if not can_action("Reassign Team Tasks", actor):
        return False
    prior_roles = user_roles(prior_user) if prior_user else set()
    from marina_custom_apps.design_management.security.participants import is_participant
    if not is_participant(new_user):
        return False
    target_roles = user_roles(new_user)
    if not target_roles:
        return False
    for manager in manager_roles(actor):
        subtree = descendants(manager)
        if target_roles & subtree and (not prior_user or prior_roles & subtree):
            return True
    return False
