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
    "Marina Fashion Category", "Production Colorway",
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
