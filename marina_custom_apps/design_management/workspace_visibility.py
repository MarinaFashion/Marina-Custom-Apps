"""Role-scoped navigation for the Marina Design Management workspace.

This module changes navigation only. Frappe native permission checks and
Marina document/action permissions continue to authorize actual operations.
"""
import json

import frappe

from marina_custom_apps.design_management.security.organization import user_roles

WORKSPACE = "Marina Design Management"
WORKSPACE_ITEMS = frozenset({
    "Management Dashboard", "Mood Boards", "Design Codes", "Design Documents",
    "Production Follow-Up Grid", "Design Discussions", "Pantone Library",
    "Fashion Categories", "Document Types", "Milestone Types",
    "Design Management Settings", "Security & Permissions",
    "Role Hierarchy", "Factory List", "Mood Board Overview",
})

# A destination is a more stable identity than its translated UI label.
ITEM_TARGETS = {
    "design-management-dashboard": "Management Dashboard",
    "Mood Board": "Mood Boards",
    "Design Code": "Design Codes",
    "Design Document": "Design Documents",
    "design-followup-grid": "Production Follow-Up Grid",
    "design-discussions": "Design Discussions",
    "Marina Pantone": "Pantone Library",
    "Marina Fashion Category": "Fashion Categories",
    "Design Document Type": "Document Types",
    "Design Milestone Type": "Milestone Types",
    "Design Management Settings": "Design Management Settings",
    "design-security-permissions": "Security & Permissions",
    "design-role-hierarchy": "Role Hierarchy",
    "Factory List": "Factory List",
    "Mood Board Overview": "Mood Board Overview",
}


def _item_name(row):
    return ITEM_TARGETS.get(row.get("link_to"), row.get("label"))


# Safe defaults until a workspace item has explicitly configured rules.
DEFAULT_RESTRICTED = {
    "Management Dashboard": frozenset({"Head Of Design", "Administrator"}),
    "Design Management Settings": frozenset({"Administrator"}),
    "Security & Permissions": frozenset({"Administrator"}),
    "Role Hierarchy": frozenset({"Administrator", "Head Of Design"}),
}


def _visibility(user=None):
    user = user or frappe.session.user
    # Do not use a shared global cache: impersonated users must not inherit
    # another user's visible shortcuts.
    administrator = user == "Administrator" or "System Manager" in frappe.get_roles(user)
    roles = user_roles(user) if not administrator else set()
    direct = {}
    allowed = {}
    rows = frappe.get_all(
        "Design Workspace Visibility Rule",
        filters={"parent": "Design Management Settings",
                 "parenttype": "Design Management Settings",
                 "parentfield": "workspace_visibility_rules"},
        fields=["workspace_item", "module_role"],
        limit_page_length=201,
    ) if frappe.db.table_exists("Design Workspace Visibility Rule") else []
    direct_rows = frappe.get_all(
        "Design Workspace User Visibility",
        filters={"parent": "Design Management Settings",
                 "parenttype": "Design Management Settings",
                 "parentfield": "workspace_user_visibility", "user": user},
        fields=["workspace_item", "visible"], limit_page_length=101,
    )
    for row in direct_rows:
        if row.workspace_item in WORKSPACE_ITEMS:
            direct[row.workspace_item] = bool(row.visible)
    for row in rows:
        if row.workspace_item in WORKSPACE_ITEMS:
            allowed.setdefault(row.workspace_item, set()).add(row.module_role)

    def visible(item):
        if item not in WORKSPACE_ITEMS or administrator:
            return True
        if item in direct:
            return direct[item]
        restricted = allowed.get(item, DEFAULT_RESTRICTED.get(item))
        return restricted is None or bool(roles & restricted)

    return visible


def _filter_content(raw, visible):
    try:
        blocks = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return raw
    if not isinstance(blocks, list):
        return raw
    filtered = [
        block for block in blocks
        if not (block.get("type") == "shortcut"
                and not visible((block.get("data") or {}).get("shortcut_name")))
    ]
    return json.dumps(filtered, separators=(",", ":"))


@frappe.whitelist()
def get_workspace_sidebar_items():
    """Filter only Marina's content; preserve Frappe's other workspaces."""
    from frappe.desk.desktop import get_workspace_sidebar_items as original
    result = original()
    pages = result.get("pages") or []
    target_pages = [p for p in pages if p.get("name") == WORKSPACE]
    if not target_pages:
        return result
    visible = _visibility()
    for page in target_pages:
        page["content"] = _filter_content(page.get("content"), visible)
    return result


@frappe.whitelist()
def get_desktop_page(page):
    """Filter actual shortcut and link-card results as well as layout blocks."""
    from frappe.desk.desktop import get_desktop_page as original
    result = original(page)
    if not result:
        return result
    try:
        item = json.loads(page) if isinstance(page, str) else page
    except (TypeError, ValueError):
        return result
    if not isinstance(item, dict) or item.get("name") != WORKSPACE:
        return result
    visible = _visibility()
    shortcuts = result.get("shortcuts") or {}
    if isinstance(shortcuts, dict):
        shortcuts["items"] = [
            row for row in shortcuts.get("items", [])
            if visible(_item_name(row))
        ]
    cards = result.get("cards") or {}
    if isinstance(cards, dict):
        for card in cards.get("items", []):
            if isinstance(card, dict):
                card["links"] = [
                    row for row in card.get("links", [])
                    if visible(_item_name(row))
                ]
    return result

@frappe.whitelist()
def workspace_user_matrix():
    """Settings-only read endpoint; no cross-user visibility data for ordinary staff."""
    actor = frappe.session.user
    if actor != "Administrator" and "System Manager" not in frappe.get_roles(actor):
        frappe.throw("Only System Manager may configure workspace visibility", frappe.PermissionError)
    members = frappe.get_all(
        "Design Module User Role",
        filters={"parent": "Design Management Settings",
                 "parenttype": "Design Management Settings",
                 "parentfield": "module_user_roles", "active": 1},
        pluck="user", limit_page_length=1001,
    )
    ids = sorted(set(members))
    if len(ids) > 100:
        frappe.throw("Workspace matrix supports at most 100 active module users")
    users = frappe.get_all("User", filters={
        "name": ["in", ids], "enabled": 1, "user_type": "System User"},
        fields=["name", "username"], order_by="username asc",
        limit_page_length=len(ids)) if ids else []
    # Batch-load all membership and visibility data once; never query per cell.
    role_rows = frappe.get_all(
        "Design Module User Role",
        filters={"parent": "Design Management Settings",
                 "parenttype": "Design Management Settings",
                 "parentfield": "module_user_roles",
                 "active": 1, "user": ["in", ids]},
        fields=["user", "module_role"], limit_page_length=1001,
    ) if ids else []
    from marina_custom_apps.design_management.security.organization import role_catalog
    active_roles = set(role_catalog())
    memberships = {uid: set() for uid in ids}
    for row in role_rows:
        if row.module_role in active_roles:
            memberships[row.user].add(row.module_role)
    legacy_rows = frappe.get_all(
        "Design Workspace Visibility Rule",
        filters={"parent": "Design Management Settings",
                 "parentfield": "workspace_visibility_rules"},
        fields=["workspace_item", "module_role"], limit_page_length=201) if frappe.db.table_exists("Design Workspace Visibility Rule") else []
    legacy = {}
    for row in legacy_rows:
        if row.workspace_item in WORKSPACE_ITEMS:
            legacy.setdefault(row.workspace_item, set()).add(row.module_role)
    overrides = frappe.get_all(
        "Design Workspace User Visibility",
        filters={"parent": "Design Management Settings",
                 "parentfield": "workspace_user_visibility",
                 "user": ["in", ids]},
        fields=["workspace_item", "user", "visible"], limit_page_length=1501,
    ) if ids and frappe.db.table_exists("Design Workspace User Visibility") else []
    explicit = {(row.user, row.workspace_item): bool(row.visible)
                for row in overrides if row.workspace_item in WORKSPACE_ITEMS}
    managers = set(frappe.get_all(
        "Has Role", filters={"parenttype": "User",
                            "role": "System Manager", "parent": ["in", ids]},
        pluck="parent", limit_page_length=len(ids))) if ids else set()
    fallback = {}
    for row in users:
        allowed_roles = memberships.get(row.name, set())
        is_admin = row.name == "Administrator" or row.name in managers
        fallback[row.name] = {}
        for item in sorted(WORKSPACE_ITEMS):
            restricted = legacy.get(item, DEFAULT_RESTRICTED.get(item))
            fallback[row.name][item] = (
                True if is_admin else
                explicit.get((row.name, item),
                    True if restricted is None else bool(allowed_roles & restricted))
            )
    return {"users": [{"user": row.name, "label": row.username or row.name}
                       for row in users],
            "items": sorted(WORKSPACE_ITEMS), "fallback": fallback}
