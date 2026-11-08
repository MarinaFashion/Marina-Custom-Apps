"""Module-specific RBAC, layered on top of Frappe authorization.

Opt-in only. A module permission never grants access rejected by Frappe,
the design scope hook, milestone gates, or QC separation rules.
"""
import frappe

MODULE_DOCTYPES = frozenset({
    "Mood Board", "Design Code", "Design Document", "Design Milestone Type",
    "Design Milestone Plan Entry", "Design Milestone Execution",
    "Design Milestone Custody Event", "Design Module Role",
    "Marina Fashion Category", "Marina Pantone", "Design Document Type",
    "Design Management Settings", "Design Item Creation", "Design Cleanup Log",
    "Production Colorway", "Design Cost Breakdown",
})
ACTIONS = frozenset({
    "Assign Milestones",
    "Advance Milestone Step",
    "Publish Document",
    "Remove Published Assignment",
    "Create ERPNext Items",
    "Delete Design Code",
    "Return to Milestone",
    "Clear Related Milestones",
    "Manage Role Permissions",
    "Assign Team Tasks",
    "Reassign Team Tasks",
    "Approve Design Cost Breakdown",
})
PERMISSION_TYPES = frozenset({"read", "create", "write", "delete"})
SCOPES = frozenset({"Assigned", "All"})


def enabled():
    """One Settings read per request, not per row/permission check."""
    cached = getattr(frappe.local, "_marina_rbac_enabled", None)
    if cached is not None:
        return cached
    value = bool(frappe.db.get_single_value(
        "Design Management Settings", "module_rbac_enabled"
    ))
    frappe.local._marina_rbac_enabled = value
    return value


def _admin(user):
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _role_assignments(user):
    return frappe.get_all("Design Module User Role",
        filters={"parent": "Design Management Settings",
                 "parenttype": "Design Management Settings",
                 "parentfield": "module_user_roles",
                 "active": 1, "user": user},
        pluck="module_role", limit_page_length=100)


def _effective(user):
    # Query once per request rather than per record. No global cache: changes
    # become effective on the next HTTP request without stale cross-user grants.
    cache = getattr(frappe.local, "_marina_design_rbac", None)
    if cache is None:
        cache = {}
        frappe.local._marina_design_rbac = cache
    if user in cache:
        return cache[user]
    if not frappe.db.get_value("User", user, "enabled"):
        cache[user] = (set(), set(), set())
        return cache[user]
    names = _role_assignments(user)
    permission_set, action_set, all_scope = set(), set(), set()
    if names:
        roles = frappe.get_all("Design Module Role",
            filters={"name": ["in", names], "enabled": 1},
            fields=["name", "scope"], limit_page_length=len(names))
        active = {r.name for r in roles}
        all_scope = {r.name for r in roles if r.scope == "All"}
        if active:
            docs = frappe.get_all("Design Module DocType Permission",
                filters={"parenttype": "Design Module Role",
                         "parent": ["in", list(active)]},
                fields=["parent", "resource_doctype", "read",
                        "create", "write", "delete"],
                limit_page_length=1000)
            for row in docs:
                for key in PERMISSION_TYPES:
                    if row.get(key):
                        permission_set.add((row.resource_doctype, key))
            actions = frappe.get_all("Design Module Action Permission",
                filters={"parenttype": "Design Module Role",
                         "parent": ["in", list(active)], "allowed": 1},
                pluck="action_key", limit_page_length=1000)
            action_set = set(actions)
    cache[user] = (permission_set, action_set, all_scope)
    return cache[user]


def can_doctype(doctype, permission, user=None):
    """Configured user matrix takes priority; otherwise legacy RBAC."""
    from marina_custom_apps.design_management.security.user_permissions import document_allowed
    direct = document_allowed(doctype, permission, user)
    if direct is not None:
        return direct
    if not enabled():
        return None
    user = user or frappe.session.user
    if _admin(user):
        return True
    if permission not in PERMISSION_TYPES or doctype not in MODULE_DOCTYPES:
        return False
    rights, _, _ = _effective(user)
    return (doctype, permission) in rights


def can_action(action, user=None, custodian=None):
    if action not in ACTIONS:
        return False
    user = user or frappe.session.user
    from marina_custom_apps.design_management.security.user_permissions import action_allowed
    direct = action_allowed(action, user, custodian=custodian)
    if direct is not None:
        return direct
    if _admin(user):
        return True
    if not enabled():
        return False
    _, actions, _ = _effective(user)
    return action in actions


def require_action(action, user=None):
    """Extra workflow authorization when RBAC enforcement is enabled.

    Existing business approval, ownership, evidence and QC gates still apply.
    """
    from marina_custom_apps.design_management.security.user_permissions import configured
    if (enabled() or configured(user)) and not can_action(action, user):
        frappe.throw("User does not have Design action: " + action, frappe.PermissionError)


def has_all_scope(user=None):
    user = user or frappe.session.user
    if _admin(user):
        return True
    if not enabled():
        return False
    return bool(_effective(user)[2])


def validate_module_role(doc):
    """Dynamically configured role, with one root and cycle-free reporting.

    Every new module role uses a restricted Frappe baseline role; the module's
    per-DocType and per-action permissions remain an additional restriction.
    """
    from marina_custom_apps.design_management.security.organization import (
        RESPONSIBILITY_GROUPS, role_catalog, clear_role_cache,
    )
    before = doc.get_doc_before_save() if not doc.is_new() else None
    if before and doc.role_name != before.role_name:
        frappe.throw("Role names are referenced by assignments; create a new role instead")
    name = (doc.role_name or "").strip()
    if not name or len(name) > 120 or name != doc.role_name:
        frappe.throw("Enter a valid role name, maximum 120 characters")
    # Business roles never independently grant native Frappe roles.
    # Existing legacy mappings are converted by the controlled migration.
    if doc.frappe_role != "Marina Design Participant":
        frappe.throw("All Design Module Roles must use Marina Design Participant")
    if not frappe.db.exists("Role", "Marina Design Participant"):
        frappe.throw("The Marina Design Participant base role is missing")
    if doc.scope not in SCOPES:
        frappe.throw("Choose Assigned or All record access scope")
    if doc.role_type not in ("Manager", "Individual Contributor"):
        frappe.throw("Choose Manager or Individual Contributor")
    if doc.responsibility_group not in RESPONSIBILITY_GROUPS:
        frappe.throw("Select a valid Responsibility Group")

    # The single fixed root can be edited, but never acquire a parent.
    parent = doc.get("reports_to_role")
    if name == "Administrator":
        if parent:
            frappe.throw("The root Administrator role cannot report to another role")
        if doc.role_type != "Manager" or not doc.enabled:
            frappe.throw("The root Administrator must remain an enabled Manager")
    elif doc.enabled:
        if not parent or parent == name:
            frappe.throw("An enabled role must report to another Manager role")
    if parent:
        # Load the hierarchy once rather than querying the database at
        # every ancestor. This is cheap even for a large Design organization.
        roles = frappe.get_all("Design Module Role",
            fields=["name", "enabled", "role_type", "reports_to_role"],
            limit_page_length=501)
        if len(roles) > 500:
            frappe.throw("Too many module roles; contact the system administrator")
        by_name = {row.name: row for row in roles}
        manager = by_name.get(parent)
        if not manager or not manager.enabled or manager.role_type != "Manager":
            frappe.throw("Reports To Role must be an enabled Manager")
        visited = {name}
        current = parent
        while current:
            if current in visited:
                frappe.throw("Circular role reporting hierarchy is not allowed")
            visited.add(current)
            if current not in by_name:
                frappe.throw("Missing reporting role in the hierarchy")
            current = by_name[current].reports_to_role
    if before and before.enabled and not doc.enabled:
        if frappe.db.exists("Design Module User Role", {
            "parent": "Design Management Settings", "parentfield": "module_user_roles",
            "module_role": doc.name, "active": 1,
        }):
            frappe.throw("Deactivate active user assignments before disabling this role")
        if frappe.db.exists("Design Module Role", {
            "reports_to_role": doc.name, "enabled": 1,
        }):
            frappe.throw("Reassign dependent child roles before disabling this Manager")
    if before and before.role_type == "Manager" and doc.role_type != "Manager":
        if frappe.db.exists("Design Module Role", {
            "reports_to_role": doc.name, "enabled": 1,
        }):
            frappe.throw("Cannot change a Manager with subordinate roles into an Individual Contributor")
    seen = set()
    for row in doc.get("doctype_permissions") or []:
        if row.resource_doctype not in MODULE_DOCTYPES or row.resource_doctype in seen:
            frappe.throw("Invalid or duplicate module DocType permission")
        seen.add(row.resource_doctype)
    seen = set()
    for row in doc.get("action_permissions") or []:
        if row.action_key not in ACTIONS or row.action_key in seen:
            frappe.throw("Invalid or duplicate workflow action")
        seen.add(row.action_key)


def validate_settings(settings):
    from marina_custom_apps.design_management.security.participants import require_participants
    user_roles = settings.get("module_user_roles") or []
    # Newly selected/active members must already have the standard ERPNext
    # role. The module's existing role sync still preserves owned grants.
    require_participants(row.user for row in user_roles if row.active)
    seen = set()
    for row in user_roles:
        key = (row.user, row.module_role)
        if key in seen:
            frappe.throw("Duplicate module role assignment for user " + str(row.user))
        seen.add(key)
        role_info = frappe.db.get_value(
            "Design Module Role", row.module_role, ["name", "enabled"], as_dict=True
        )
        if not role_info:
            frappe.throw("Unknown Design Module Role: " + str(row.module_role))
        if row.active and settings.module_rbac_enabled and not role_info.enabled:
            frappe.throw("Cannot enable an inactive module role assignment: " + str(row.module_role))
        if row.active:
            user_data = frappe.db.get_value(
                "User", row.user, ["enabled", "user_type", "username"], as_dict=True)
            if not user_data or not user_data.enabled:
                frappe.throw("Inactive user cannot hold active module role")
            if user_data.user_type != "System User":
                frappe.throw("Module roles may be assigned only to ERPNext System Users")
            if not (user_data.username or "").strip():
                frappe.throw("Configure User Name on the ERPNext User before assigning a module role")
    if settings.module_rbac_enabled:
        # The System Manager is an emergency administrator bypass.
        if not any(row.active for row in user_roles):
            frappe.throw("Assign active module roles before enabling enforcement")
        if not frappe.db.exists("Design Module Role", {"enabled": 1}):
            frappe.throw("Create and enable a module role before enabling enforcement")
