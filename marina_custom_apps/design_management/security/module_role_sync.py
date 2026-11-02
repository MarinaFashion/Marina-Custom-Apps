"""Grant one ERPNext base role from module users; remove only module-owned grants.

Never delete a manually assigned ERPNext role, nor touch unrelated roles.
Changes to Module User Roles are synchronized when Settings is saved.
"""
import frappe
from frappe.utils import now_datetime

BASE_ROLE = "Marina Design Participant"


def sync_user_roles(settings, before, force=False):
    """Reconcile grants, preserving pre-existing/manual roles.

    force=True is used once after converting legacy module role mappings.
    The grant ledger proves which old ERPNext roles this application owns.
    """
    current = {(r.user, r.module_role, int(r.active or 0))
               for r in (settings.get("module_user_roles") or [])}
    old = {(r.user, r.module_role, int(r.active or 0))
           for r in (before.get("module_user_roles") or [])} if before else set()
    active_now = bool(settings.module_rbac_enabled)
    active_before = bool(before.module_rbac_enabled) if before else False
    if current == old and active_now == active_before and not force:
        return

    # Normal user-role edits only need to touch changed users.
    # Enabling RBAC or a one-time migration reconciles all assigned users.
    affected = (current | old) if (force or active_now != active_before) else (current ^ old)
    users = {r[0] for r in affected}
    if len(users) > 200:
        frappe.throw("Maximum of 200 affected module users per Settings update")

    role_names = {r[1] for r in current | old}
    active_roles = set(frappe.get_all(
        "Design Module Role",
        filters={"name": ["in", sorted(role_names)], "enabled": 1},
        pluck="name", limit_page_length=max(len(role_names), 1)
    )) if role_names else set()

    # A single participant role per active user, regardless of how many
    # distinct business roles the user holds. Never grant System Manager.
    for user in sorted(users):
        is_participant = active_now and any(
            u == user and active and role in active_roles
            for u, role, active in current
        )
        desired = {BASE_ROLE} if is_participant else set()
        rows = frappe.get_all("Design Module Managed Grant",
            filters={"user": user}, fields=["name", "frappe_role"],
            limit_page_length=101)
        if len(rows) > 100:
            frappe.throw("Too many tracked Design grants for user " + user)
        ledger_by_role = {row.frappe_role: row.name for row in rows}
        user_doc = frappe.get_doc("User", user)
        existing = {row.role for row in user_doc.get("roles") or []}
        add = desired - existing
        # Delete roles only if the module's ledger recorded its own grant.
        # Manual roles (even old Marina roles) are retained for later review.
        remove = set(ledger_by_role) - desired
        remove_existing = remove & existing
        if not add and not remove:
            continue

        for role in sorted(add):
            user_doc.append("roles", {"role": role})
        if remove_existing:
            user_doc.set("roles", [
                row for row in (user_doc.get("roles") or [])
                if row.role not in remove_existing
            ])
        if add or remove_existing:
            user_doc.save(ignore_permissions=True)
        for role in sorted(add):
            frappe.get_doc({
                "doctype": "Design Module Managed Grant",
                "user": user, "frappe_role": role, "added_on": now_datetime(),
            }).insert(ignore_permissions=True)
        for role in sorted(remove):
            frappe.delete_doc("Design Module Managed Grant",
                              ledger_by_role[role], ignore_permissions=True)
        frappe.clear_cache(user=user)

    from marina_custom_apps.design_management.security.organization import clear_role_cache
    clear_role_cache()
