"""Mood Board eligible staff pool and one responsible employee per Design role."""
import frappe

from marina_custom_apps.design_management.clean_milestones.team_selection import (
    active_pools, choose_design_assignments, value,
)
from marina_custom_apps.design_management.security.organization import (
    role_catalog, user_roles, can_manage_role,
)
from marina_custom_apps.design_management.security.role_access import can_action
from marina_custom_apps.design_management.security.participants import require_participants


# Exact six-role baseline approved for Mood Board Team Pool.
# A 0 Default is intentional for Designer, matching the form template.
MOOD_BOARD_BASE_ROLES = (
    ("Designer", 0),
    ("Merchandiser", 1),
    ("Fabric Sourcing", 1),
    ("QC Officer", 1),
    ("Shipping Coordinator", 1),
    ("Technical Fitting Officer", 1),
)


@frappe.whitelist()
def get_mood_board_base_roles(mood_board=None):
    """Authorize the template and verify its six Design Module Role links.

    Does not create or save any rows. The client inserts only absent roles,
    so current assignments, extra users and custom defaults are preserved.
    """
    actor = frappe.session.user
    if mood_board:
        board = frappe.get_doc("Mood Board", mood_board)
        board.check_permission("write")
    else:
        if not frappe.has_permission("Mood Board", "create"):
            frappe.throw("Not permitted to create a Mood Board",
                         frappe.PermissionError)

    settings = frappe.get_cached_doc("Design Management Settings")
    custom = bool(settings.use_custom_mood_board_team_template)
    if custom:
        template = [
            {"module_role": row.module_role, "user": row.user,
             "active": 1, "default_for_design": int(row.default_for_design or 0)}
            for row in (settings.mood_board_base_team or []) if row.active
        ]
    else:
        template = [
            {"module_role": role, "user": None, "active": 1,
             "default_for_design": default}
            for role, default in MOOD_BOARD_BASE_ROLES
        ]
    wanted = sorted({row["module_role"] for row in template})
    # Reading an administrator-approved template is not reassignment.
    # Native Mood Board create/write permission is checked above; actual
    # team edits are independently authorized in validate_board().
    catalog = role_catalog()
    missing = [role for role in wanted if role not in catalog]
    if missing:
        frappe.throw("Enable these Design Module Roles first: " + ", ".join(missing))
    if custom:
        from marina_custom_apps.design_management.security.participants import is_participant
        for row in template:
            if not is_participant(row["user"]) or row["module_role"] not in user_roles(row["user"]):
                frappe.throw("Configured Base Team user is no longer eligible for " + row["module_role"])
    return template


def _admin(actor):
    return actor == "Administrator" or "System Manager" in frappe.get_roles(actor)


def validate_rows(rows, *, allow_role_pool=False):
    users = list(rows or [])
    if len(users) > 100:
        frappe.throw("Too many Design Team members (maximum 100)")
    try:
        pools = active_pools(users)
    except ValueError as exc:
        frappe.throw(str(exc))
    if not allow_role_pool and any(len(members) != 1 for members in pools.values()):
        frappe.throw("Assign exactly one active employee per Module Role on the Design Code")
    # Native ERPNext membership is mandatory in addition to Design
    # business-role assignments. Do not rewrite inactive historical rows.
    require_participants(row.user for members in pools.values() for row in members)
    catalog = role_catalog()
    for role, members in pools.items():
        if role not in catalog:
            frappe.throw("Invalid or disabled Module Role: " + role)
        for row in members:
            if role not in user_roles(row.user) or not frappe.db.get_value(
                    "User", row.user, "enabled"):
                frappe.throw("User must be active and hold Module Role " + role)


def _changes(before, after):
    def identity(rows):
        return {(r.module_role, r.user, bool(r.active),
                 bool(value(r, "default_for_design", 0)))
                for r in (rows or []) if r.module_role}
    return {row[0] for row in identity(before) ^ identity(after)}


def _manager_may_change(doc, changes):
    if not changes:
        return
    actor = frappe.session.user
    if _admin(actor):
        return
    action = "Assign Team Tasks" if doc.is_new() else "Reassign Team Tasks"
    if not can_action(action, actor) or not all(
            can_manage_role(actor, role) for role in changes):
        frappe.throw("Only authorized team management can change assigned employees",
                     frappe.PermissionError)
    if not doc.is_new():
        for role in changes:
            if not any(row.module_role == role
                       and len((row.assignment_note or "").strip()) >= 5
                       for row in (doc.get("r22_team_assignments") or [])):
                frappe.throw("Record a reason when changing the " + role +
                             " Design Team assignment")


def _unapproved_board_changes(before, after):
    """Exclude only NEW, active entries explicitly approved in the settings template.

    No removal, replacement, deactivation, or change to existing defaults is
    exempt. Newly inserted rows may have their configured default unchecked
    if that role already has a default on the Mood Board.
    """
    from collections import Counter

    def signature(row):
        return (row.module_role, row.user, bool(row.active),
                bool(value(row, "default_for_design", 0)))

    prior = Counter(signature(row) for row in (before or []))
    current = Counter(signature(row) for row in (after or []))
    removed = prior - current
    added = current - prior

    settings = frappe.get_cached_doc("Design Management Settings")
    approved = set()
    if settings.use_custom_mood_board_team_template:
        for row in (settings.mood_board_base_team or []):
            if row.active and row.module_role and row.user:
                approved.add((row.module_role, row.user,
                              bool(row.default_for_design)))

    # A row with a disabled default can be added even when the base template
    # specifies a default; this avoids a duplicate default on existing boards.
    changes = {role for (role, _, _, _), count in removed.items() if count}
    for (role, user, active, default), count in added.items():
        if not active or not any(
                role == target_role and user == target_user
                and (not default or target_default)
                for target_role, target_user, target_default in approved
        ):
            changes.add(role)
    return changes


def validate_board(board):
    rows = board.get("r22_team_assignments") or []
    validate_rows(rows, allow_role_pool=True)
    before = board.get_doc_before_save() if not board.is_new() else None
    prior = before.get("r22_team_assignments") if before else []
    _manager_may_change(board, _unapproved_board_changes(prior, rows))


def initial_snapshot_rows(board):
    """Use the Mood Board pool and explicit defaults, never arbitrary users.

    The same computation supplies the unsaved form preview and the server
    validation baseline. There is only one selected employee per Module Role.
    """
    pool = board.get("r22_team_assignments") or []
    validate_rows(pool, allow_role_pool=True)
    try:
        chosen = choose_design_assignments(pool)
    except ValueError as exc:
        frappe.throw(str(exc))
    # A Designer is selected for EACH Design Code, never inherited from
    # the Mood Board, even when there is just one eligible Designer or a
    # Mood Board default. Other role defaults retain their existing rules.
    chosen.pop("Designer", None)
    return [
        {"module_role": role, "user": user, "active": 1,
         "default_for_design": 1,
         "assignment_note": "Selected from Mood Board Team Pool on creation"}
        for role, user in chosen.items()
    ]


@frappe.whitelist()
def preview_mood_board_team(mood_board):
    """Return only the team of one Mood Board the actor may read."""
    if not isinstance(mood_board, str) or not mood_board or len(mood_board) > 140:
        frappe.throw("Select a Mood Board")
    board = frappe.get_doc("Mood Board", mood_board)
    board.check_permission("read")
    assignments = initial_snapshot_rows(board)
    from marina_custom_apps.design_management.api.user_display import usernames_for_user_ids
    titles = usernames_for_user_ids(
        (row["user"] for row in assignments), max_users=100)
    # Display labels only; Design Team Assignment continues storing User IDs.
    for row in assignments:
        row["user_username"] = titles.get(
            row["user"], "Username not configured")
    return assignments


def snapshot_design(design):
    """Populate once when necessary; never overwrite edits made before Save.

    On a new Design the Mood Board defaults are the baseline. Any change to
    that baseline (including an added/removed role) requires manager authority.
    A client-supplied snapshot marker does not bypass that check.
    """
    if not design.is_new() or not design.mood_board:
        return
    board = frappe.get_doc("Mood Board", design.mood_board)
    board.check_permission("read")
    initial = initial_snapshot_rows(board)
    incoming = design.get("r22_team_assignments") or []
    if not incoming and not design.r22_team_snapshot_applied:
        design.set("r22_team_assignments", initial)
    else:
        baseline = [frappe._dict(row) for row in initial]
        _manager_may_change(design, _changes(baseline, incoming))
    design.r22_team_snapshot_applied = 1


def sync_legacy_owners(design):
    """Keep legacy report/search fields as read-only projections of the team.

    Never treat these fields as editable assignment authority. This does not
    create or reassign child rows, and cannot bypass team RBAC validation.
    """
    by_role = {
        row.module_role: row.user for row in
        (design.get("r22_team_assignments") or [])
        if row.active and row.module_role and row.user
    }
    for field, role in (
        ("assigned_merchandiser", "Merchandiser"),
        ("designer", "Designer"),
        ("technical_fitting_responsible", "Technical Fitting Officer"),
    ):
        design.set(field, by_role.get(role))




def _active_custody_rows(design):
    """Bounded active work lookup; no per-role/per-milestone database calls."""
    plans = frappe.get_all(
        "Design Milestone Plan Entry",
        filters={"design_code": design.name, "plan_state": "Active"},
        fields=["name", "activated_execution"], limit_page_length=51,
    )
    if len(plans) > 50:
        frappe.throw("Too many active milestone plans to update custody")
    ids = {p.activated_execution for p in plans if p.activated_execution}
    if not ids:
        return []
    executions = frappe.get_all(
        "Design Milestone Execution",
        filters={"name": ["in", sorted(ids)], "design_code": design.name},
        fields=["name", "plan_entry", "status", "current_role",
                "current_custodian"],
        limit_page_length=len(ids),
    )
    if len(executions) != len(ids):
        frappe.throw("Active milestone execution mismatch; reload the Design")
    by_id = {row.name: row for row in executions}
    for plan in plans:
        if plan.activated_execution:
            execution = by_id.get(plan.activated_execution)
            if not execution or execution.plan_entry != plan.name:
                frappe.throw("Milestone execution link mismatch; reload the Design")
    return executions


def _changed_active_owners(design, changes):
    owners = {
        r.module_role: r.user for r in design.get("r22_team_assignments") or []
        if r.active and r.module_role and r.user
    }
    current = []
    for execution in _active_custody_rows(design):
        if execution.current_role not in changes:
            continue
        next_owner = owners.get(execution.current_role)
        if not next_owner:
            frappe.throw(
                "Cannot remove " + execution.current_role +
                " while an active milestone is in its custody. Assign a replacement first.")
        if execution.current_custodian != next_owner:
            current.append((execution, next_owner))
    return current


def sync_active_custody(design):
    """Transfer custody only for changed active roles and append audit events.

    A child's selected user is authoritative. Completed and Future milestone
    executions are not rewritten, and historical events are never removed.
    """
    if design.is_new():
        return
    before = design.get_doc_before_save()
    if not before:
        return
    changed = _changes(before.get("r22_team_assignments") or [],
                       design.get("r22_team_assignments") or [])
    if not changed:
        return
    current = _changed_active_owners(design, changed)
    if not current:
        return
    from frappe.utils import now_datetime
    from marina_custom_apps.design_management.clean_milestones.service import _event
    notes = {
        row.module_role: (row.assignment_note or "").strip()
        for row in (design.get("r22_team_assignments") or []) if row.active
    }
    moment = now_datetime()
    for exe, new_user in current:
        frappe.db.set_value("Design Milestone Execution", exe.name, {
            "current_custodian": new_user, "last_action_on": moment,
        }, update_modified=False)
        updated = frappe._dict(
            name=exe.name, status=exe.status, current_custodian=new_user)
        _event(design, frappe._dict(name=exe.plan_entry), updated,
               "Custody Reassigned", old=exe.status,
               prior=exe.current_custodian, reason=notes.get(
                   exe.current_role) or "Design Team assignment updated")


def validate_design(design):
    rows = design.get("r22_team_assignments") or []
    validate_rows(rows)
    if design.is_new():
        if not design.r22_team_snapshot_applied:
            frappe.throw("The Design Team has not been copied from Mood Board")
        return
    previous = design.get_doc_before_save()
    if previous and previous.r22_team_snapshot_applied and not design.r22_team_snapshot_applied:
        frappe.throw("Design Team snapshot marker cannot be removed")
    changed = _changes(
        previous.get("r22_team_assignments") if previous else [], rows)
    _manager_may_change(design, changed)
    if changed:
        # Fail before saving if an in-progress milestone would lose custody.
        _changed_active_owners(design, changed)
