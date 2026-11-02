"""Central ERPNext User eligibility for Marina Design Management.

Marina Design Participant is a *standard ERPNext Role* (tabHas Role), not a
Design Module Role. Link selectors additionally honour module business roles
where relevant. Read-only audit/history owners are deliberately not rewritten.
"""
import frappe

BASE_ROLE = "Marina Design Participant"
MAX_CANDIDATES = 1000


def participant_ids(user_ids):
    """One bounded indexed Has Role lookup for a set of User IDs."""
    ids = sorted({u for u in (user_ids or []) if isinstance(u, str) and u})
    if not ids:
        return set()
    if len(ids) > MAX_CANDIDATES:
        frappe.throw("Too many Design user candidates")
    return set(frappe.get_all(
        "Has Role",
        filters={
            "parenttype": "User",
            "parent": ["in", ids],
            "role": BASE_ROLE,
        },
        pluck="parent",
        limit_page_length=len(ids),
    ))


def is_participant(user):
    """An active, non-Guest ERPNext System User with the required role."""
    if not user or user == "Guest":
        return False
    # The milestone engine resolves custody for many steps in one request.
    # Cache each user's eligibility for this request only (not across users
    # or HTTP requests), avoiding repeated Has Role lookups.
    local = getattr(frappe, "local", None)
    cache = getattr(local, "_marina_participant_checks", None)
    if cache is not None and user in cache:
        return cache[user]
    details = frappe.db.get_value(
        "User", user, ["enabled", "user_type"], as_dict=True)
    allowed = bool(
        details and details.enabled and details.user_type == "System User"
        and frappe.db.exists("Has Role", {
            "parenttype": "User", "parent": user, "role": BASE_ROLE,
        })
    )
    if local is not None:
        if cache is None:
            cache = {}
            local._marina_participant_checks = cache
        cache[user] = allowed
    return allowed


def require_participants(users):
    """Reject new/active team selections that lack the native ERPNext role.

    Call in parent DocType validation and when a server-side change assigns a
    custodian. Single batch query prevents a per-row role lookup.
    """
    ids = {u for u in (users or []) if u}
    missing = ids - participant_ids(ids)
    if missing:
        frappe.throw(
            "Only users assigned ERPNext role '" + BASE_ROLE +
            "' may be selected in Marina Design Management: " +
            ", ".join(sorted(missing)[:10])
        )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_participant_users(doctype, txt, searchfield, start, page_len, filters):
    """Frappe User Link query; search names only within active participants.

    Additional optional module_role or owner_field criteria restrict Design
    responsibilities to their configured module roles. No User list is leaked
    to callers without read access to a Design module DocType.
    """
    if doctype != "User":
        return []
    if not any(frappe.has_permission(dt, "read") for dt in (
        "Design Code", "Mood Board", "Design Management Settings",
        "Design Document", "Design Milestone Execution",
    )):
        return []

    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    filters = filters or {}
    if not isinstance(filters, dict):
        return []
    module_role = filters.get("module_role")
    owner_field = filters.get("owner_field")
    if module_role and owner_field:
        return []

    roles = []
    if owner_field:
        from marina_custom_apps.design_management.security.organization import owner_roles
        roles = sorted(owner_roles(owner_field))
        if not roles:
            return []
    elif module_role:
        if not isinstance(module_role, str) or len(module_role) > 140:
            return []
        from marina_custom_apps.design_management.security.organization import role_catalog
        if module_role not in role_catalog():
            return []
        roles = [module_role]

    conditions = [
        "u.enabled=1", "u.user_type='System User'",
        "EXISTS (SELECT 1 FROM `tabHas Role` hr "
        "WHERE hr.parent=u.name AND hr.parenttype='User' AND hr.role=%s)",
        "(u.name LIKE %s OR u.username LIKE %s OR u.full_name LIKE %s)",
    ]
    term = "%" + (txt or "").strip() + "%"
    params = [BASE_ROLE, term, term, term]
    if roles:
        placeholders = ", ".join(["%s"] * len(roles))
        conditions.append(
            "EXISTS (SELECT 1 FROM `tabDesign Module User Role` mr "
            "WHERE mr.user=u.name AND mr.active=1 "
            "AND mr.parent='Design Management Settings' "
            "AND mr.parenttype='Design Management Settings' "
            "AND mr.parentfield='module_user_roles' "
            "AND mr.module_role IN (" + placeholders + "))"
        )
        params.extend(roles)
    # Bounded paging; never enumerate all ERPNext users in a Link picker.
    offset = max(0, min(int(start), 10000))
    limit = max(1, min(int(page_len), 50))
    params.extend((limit, offset))
    return frappe.db.sql(
        "SELECT u.name, COALESCE(NULLIF(u.username,''),u.name) "
        "FROM `tabUser` u WHERE " + " AND ".join(conditions) +
        " ORDER BY u.username, u.name LIMIT %s OFFSET %s",
        tuple(params),
    )
