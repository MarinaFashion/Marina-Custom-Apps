"""Per-user Design permissions. Unconfigured users keep legacy behavior.

Each request caches one user's matrix. No global cache or per-row SQL calls.
A configured user receives explicit permission decisions, not module-role unions.
Native Frappe DocType access, valid user/custody, and business invariants still apply.
"""
import frappe

POLICY_DOCTYPE = "Design User Permission"
DOCS = frozenset({
    "Mood Board", "Design Code", "Design Document", "Design Cost Breakdown",
    "Design Milestone Type", "Design Milestone Plan Entry",
    "Design Milestone Execution", "Design Milestone Custody Event",
    "Design Document Type", "Design Item Creation", "Marina Pantone",
    "Marina Fashion Category", "Factory List", "Production Colorway",
    # Business-role metadata is a selectable reference for Design Team rows.
    # Read/Select must be configurable separately from administrative edits.
    "Design Module Role",
})
ACTIONS = frozenset({
    "Assign Milestones", "Advance Milestone Step", "Publish Document",
    "Remove Published Assignment", "Create ERPNext Items", "Delete Design Code",
    "Return to Milestone", "Clear Related Milestones", "Manage Role Permissions",
    "Assign Team Tasks", "Reassign Team Tasks", "Approve Design Cost Breakdown",
    "Send Discussion Message", "Upload Discussion Attachment",
})
CUSTODY_ACTIONS = frozenset({"Advance Milestone Step"})
OPERATIONS = frozenset({"read", "create", "write", "delete"})


def _policy(user):
    cache = getattr(frappe.local, "_marina_user_permissions", None)
    if cache is None:
        cache = {}
        frappe.local._marina_user_permissions = cache
    if user in cache:
        return cache[user]
    result = None
    if (user and user != "Guest"
            and frappe.db.exists("DocType", POLICY_DOCTYPE)
            and frappe.db.table_exists(POLICY_DOCTYPE)
            and frappe.db.exists(POLICY_DOCTYPE, user)
            and frappe.db.get_value("User", user, "enabled")):
        policy = frappe.get_doc(POLICY_DOCTYPE, user)
        if policy.enabled:
            docs = {}
            actions = {}
            for row in policy.get("document_permissions") or []:
                docs[row.resource_doctype] = {
                    key: bool(row.get(key)) for key in OPERATIONS
                }
            for row in policy.get("action_permissions") or []:
                actions[row.action_key] = row.access
            result = (docs, actions)
    cache[user] = result
    return result


def configured(user=None):
    return _policy(user or frappe.session.user) is not None


def document_allowed(doctype, permission, user=None):
    """None when unconfigured; otherwise True/False (explicit missing=deny)."""
    user = user or frappe.session.user
    policy = _policy(user)
    if policy is None:
        return None
    if doctype not in DOCS or permission not in OPERATIONS:
        return False
    return policy[0].get(doctype, {}).get(permission, False)


def action_allowed(action, user=None, custodian=None):
    """None when unconfigured; custody restriction uses current execution owner."""
    user = user or frappe.session.user
    policy = _policy(user)
    if policy is None:
        return None
    mode = policy[1].get(action, "Not Allowed")
    if mode == "Allowed":
        return True
    if mode == "Custody Only":
        return action in CUSTODY_ACTIONS and bool(custodian) and custodian == user
    return False


def invalidate():
    if hasattr(frappe.local, "_marina_user_permissions"):
        delattr(frappe.local, "_marina_user_permissions")


@frappe.whitelist()
def permission_catalog():
    """Server-authoritative document/action choices for the permission editor.

    Only administrators can configure this data. Avoid emitting noninstalled
    DocTypes; absent permissions remain denied in an enabled profile.
    """
    if (frappe.session.user != "Administrator"
            and "System Manager" not in frappe.get_roles(frappe.session.user)):
        frappe.throw("System Manager required", frappe.PermissionError)
    return {
        "documents": [
            name for name in sorted(DOCS) if frappe.db.exists("DocType", name)
        ],
        "actions": [
            {"name": name, "custody_supported": name in CUSTODY_ACTIONS}
            for name in sorted(ACTIONS)
        ],
    }


@frappe.whitelist()
def preview_user_permissions(user):
    """Admin-only preview: configured rights and native Frappe access side by side.

    This does NOT simulate record-specific custody, workflow state or a
    transaction. Use a real Design Code for those integration tests.
    """
    if (frappe.session.user != "Administrator"
            and "System Manager" not in frappe.get_roles(frappe.session.user)):
        frappe.throw("Only System Manager may inspect user permissions",
                     frappe.PermissionError)
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("Choose an enabled user")
    from marina_custom_apps.design_management.security.role_access import can_action
    docs = []
    for doctype in sorted(DOCS):
        if not frappe.db.exists("DocType", doctype):
            continue
        rights = {}
        for op in sorted(OPERATIONS):
            explicit = document_allowed(doctype, op, user)
            native = bool(frappe.has_permission(
                doctype, op, user=user, throw=False))
            rights[op] = {
                "individual": explicit,
                "native": native,
                "effective": native and explicit is not False,
            }
        docs.append({"doctype": doctype, "rights": rights})
    actions = {}
    for action in sorted(ACTIONS):
        decision = action_allowed(action, user=user)
        actions[action] = {
            "individual": decision,
            "allowed_without_custody": bool(can_action(action, user)),
            "custody_only": bool(
                _policy(user) is not None
                and _policy(user)[1].get(action) == "Custody Only"
            ),
        }
    return {
        "user": user, "individual_profile_enabled": configured(user),
        "documents": docs, "actions": actions,
        "note": "Record scope, valid custody and workflow rules are checked during operations.",
    }
