"""Permission-scoped grouped design milestone grid.

The grid is a view over the clean milestone engine, never a second workflow.
Design scope is established with Frappe get_list (not get_all), then bounded
batch reads are restricted to those accessible Design Code IDs.
"""
import json

import frappe
from frappe.utils import now_datetime, today
from marina_custom_apps.design_management.clean_milestones.schedule import (
    projected_dates, rolling_projected_dates, baseline_progress,
)
from marina_custom_apps.design_management.security.organization import (
    descendants, manager_roles,
)
from marina_custom_apps.design_management.security.role_access import can_action
from marina_custom_apps.design_management.clean_milestones.design_code_filter import (
    parse_design_codes, restrict_to_design_codes,
)

MAX_DESIGNS = 100
MAX_PLANS_PER_DESIGN = 50
MAX_CUSTODY_DESIGNS = 20000


def _custody_design_names(user_id, plan_state=None):
    """Indexed, bounded custody lookup; Design Code get_list enforces scope.

    The execution rows are only candidate IDs. Never return them to users
    without the normal permission-aware Design Code query.
    """
    filters = {"current_custodian": user_id}
    if plan_state:
        # State-aware matching happens BEFORE Design Code pagination; a
        # Current + Assigned to Me page cannot be filled with historical
        # Completed plans. Future plans have no active custody.
        if plan_state == "Planned":
            return []
        results = frappe.db.sql("""
            SELECT DISTINCT e.design_code
            FROM `tabDesign Milestone Execution` e
            INNER JOIN `tabDesign Milestone Plan Entry` p
                ON p.name = e.plan_entry
            WHERE e.current_custodian = %s
              AND p.plan_state = %s
            LIMIT %s
        """, (user_id, plan_state, MAX_CUSTODY_DESIGNS + 1), as_dict=True)
        names = [row.design_code for row in results]
    else:
        rows = frappe.get_all(
            "Design Milestone Execution",
            filters=filters, fields=["design_code"],
            limit_page_length=MAX_CUSTODY_DESIGNS + 1,
        )
        names = [row.design_code for row in rows]
    if len(names) > MAX_CUSTODY_DESIGNS:
        frappe.throw("Too many custody assignments. Narrow the selection.")
    return sorted(set(names))


@frappe.whitelist()
def has_my_current_custody():
    """One lightweight check before defaulting Custody to Assigned to Me."""
    if not frappe.has_permission("Design Code", "read"):
        return False
    user = frappe.session.user
    if not user or user == "Guest":
        return False
    candidates = _custody_design_names(user, plan_state="Active")
    if not candidates:
        return False
    readable = frappe.get_list(
        "Design Code",
        filters={"name": ["in", candidates]},
        fields=["name"], limit_page_length=1,
    )
    return bool(readable)


def _actor_access():
    from marina_custom_apps.design_management.clean_milestones.service import _is_admin
    from marina_custom_apps.design_management.security.user_permissions import configured
    user = frappe.session.user
    individualized = configured(user)
    admin = _is_admin(user) and not individualized
    action = (admin or can_action("Advance Milestone Step", user)
              or (individualized and can_action(
                  "Advance Milestone Step", user, custodian=user)))
    scope = set()
    if admin or individualized:
        return admin, action, scope
    if (can_action("Assign Team Tasks", user) or
            can_action("Reassign Team Tasks", user)):
        for role in manager_roles(user):
            scope.update(descendants(role))
    return admin, action, scope


def _allowed_rows(designs, plans, executions):
    from marina_custom_apps.design_management.clean_milestones.service import _next_allowed
    names = [r.name for r in designs]
    user = frappe.session.user
    admin, can_advance, manager_scope = _actor_access()
    from marina_custom_apps.design_management.security.user_permissions import configured
    individualized = configured(user)
    assigned = set()
    if names and can_advance and not admin:
        members = frappe.get_all("Design Team Assignment",
            filters={"parenttype": "Design Code",
                     "parentfield": "r22_team_assignments",
                     "active": 1, "user": user,
                     "parent": ["in", names]},
            fields=["parent", "module_role"],
            limit_page_length=MAX_DESIGNS * 12)
        assigned = {(x.parent, x.module_role) for x in members}
    by_plan = {r.plan_entry: r for r in executions}
    grouped = {name: [] for name in names}
    for plan in plans:
        exe = by_plan.get(plan.name)
        row = {"milestone_type": plan.milestone_type,
               "sequence": plan.sequence,
               "plan_state": plan.plan_state,
               "trigger_milestone": plan.depends_on_type,
               "trigger_step": plan.trigger_status,
               "execution": None, "status": "Planned",
               "note": "", "due_date": None, "completion_date": None,
               "current_custodian": None, "current_role": None,
               "evidence_document": None, "step_entered_on": None,
               "rework_count": 0, "can_note": False, "allowed_steps": [],
               "evidence_types": {}}
        if exe and plan.plan_state != "Planned":
            row.update({"execution": exe.name, "status": exe.status,
                "note": exe.latest_note or "",
                "due_date": exe.due_date,
                "current_custodian": exe.current_custodian,
                "current_role": exe.current_role,
                "evidence_document": exe.evidence_document,
                "step_entered_on": exe.step_entered_on,
                # completed_on stores the effective date selected in the
                # Completed step (not the real recorded/audit timestamp).
                # Exclude old completion dates after a return/rework.
                "completion_date": (
                    str(exe.completed_on)[:10]
                    if plan.plan_state == "Completed"
                    and exe.status == "Completed" and exe.completed_on
                    else None
                ),
                "rework_count": exe.rework_count or 0})
            if exe.status != "Completed" and can_advance:
                row["can_note"] = (bool(can_action(
                    "Advance Milestone Step", user, custodian=exe.current_custodian))
                    if individualized else bool(admin or
                    (plan.design_code, exe.current_role) in assigned or
                    exe.current_role in manager_scope))
                snapshot = json.loads(plan.workflow_snapshot_json)
                for step in _next_allowed(snapshot, exe.status):
                    authorized = (bool(can_action(
                        "Advance Milestone Step", user, custodian=exe.current_custodian))
                        if individualized else (admin or
                        (plan.design_code, step["responsible_module_role"]) in assigned or
                        step["responsible_module_role"] in manager_scope))
                    if not authorized:
                        continue
                    row["allowed_steps"].append(step["step"])
                    if step["requires_evidence"]:
                        row["evidence_types"][step["step"]] = step["evidence_type"]
        grouped[plan.design_code].append(row)
    return grouped


@frappe.whitelist()
def get_grid(page=1, page_size=50, search=None, mood_board=None,
             designer=None, custody=None, milestone_view="all", factory=None,
             design_codes=None, dashboard_milestone=None,
             year=None, season=None, collection=None, drop=None,
             assigned_merchandiser=None, deadline_status=None,
             current_milestone=None, milestone_type=None):
    if not frappe.has_permission("Design Code", "read"):
        frappe.throw("Design Code read permission required", frappe.PermissionError)
    try:
        page = int(page)
        page_size = int(page_size)
    except (ValueError, TypeError):
        frappe.throw("Invalid pagination")
    if page < 1 or page > 10000 or page_size not in (20, 50, 100):
        frappe.throw("Page size must be 20, 50 or 100")
    if milestone_view not in ("all", "active", "completed", "future"):
        frappe.throw("Invalid milestone status filter")
    try:
        selected_codes = parse_design_codes(design_codes)
    except ValueError as exc:
        frappe.throw(str(exc))
    filters = {}
    if dashboard_milestone:
        if (not isinstance(dashboard_milestone, str)
                or len(dashboard_milestone) > 140
                or milestone_view not in ("active", "completed")):
            frappe.throw("Invalid dashboard milestone selection")
    for field, value in (
        ("year", year), ("season", season), ("collection", collection),
        ("drop", drop), ("assigned_merchandiser", assigned_merchandiser),
    ):
        if value:
            if not isinstance(value, str) or len(value) > 140:
                frappe.throw("Invalid " + field + " filter")
            filters[field] = value
    if mood_board:
        filters["mood_board"] = str(mood_board)[:140]
    if designer:
        filters["designer"] = str(designer)[:140]
    if factory:
        if not isinstance(factory, str) or len(factory) > 140:
            frappe.throw("Invalid Factory filter")
        filters["factory"] = factory
    if custody:
        if not isinstance(custody, str) or len(custody) > 140:
            frappe.throw("Invalid Custody filter")
        # Filter candidate designs BEFORE pagination. Do not filter only
        # the 20/50/100 designs already shown on the current page.
        plan_state = {"active": "Active", "completed": "Completed",
                      "future": "Planned"}.get(milestone_view)
        candidates = _custody_design_names(custody, plan_state=plan_state)
        if not candidates:
            return {"designs": [], "page": page,
                    "page_size": page_size, "has_more": False}
        filters["name"] = ["in", candidates]
    if not restrict_to_design_codes(filters, selected_codes):
        return {"designs": [], "page": page,
                "page_size": page_size, "has_more": False}
    if milestone_type:
        if not isinstance(milestone_type, str) or len(milestone_type) > 140:
            frappe.throw("Invalid Milestone Type filter")
        # Filter designs using milestone plans before pagination, not on the
        # already-fetched page. The selected plan state also governs rows.
        plan_state = {
            "active": "Active", "completed": "Completed", "future": "Planned"
        }.get(milestone_view)
        milestone_filters = {"milestone_type": milestone_type}
        if plan_state:
            milestone_filters["plan_state"] = plan_state
        matching_plans = frappe.get_all(
            "Design Milestone Plan Entry",
            filters=milestone_filters,
            fields=["design_code"],
            limit_page_length=MAX_CUSTODY_DESIGNS + 1,
        )
        if len(matching_plans) > MAX_CUSTODY_DESIGNS:
            frappe.throw("Too many milestone records. Narrow the filters.")
        matching_names = {row.design_code for row in matching_plans}
        if "name" in filters:
            matching_names &= set(filters["name"][1])
        if not matching_names:
            return {"designs": [], "page": page,
                    "page_size": page_size, "has_more": False}
        filters["name"] = ["in", sorted(matching_names)]
    if dashboard_milestone:
        if current_milestone:
            if not isinstance(current_milestone, str) or len(current_milestone) > 140:
                frappe.throw("Invalid dashboard Current Milestone filter")
        # Select design IDs from the same plan/execution conditions used
        # by the dashboard. Do this before pagination; per-page filtering
        # otherwise yields missing designs and incorrect navigation.
        active = milestone_view == "active"
        status_clause = "x.status!='Completed'" if active else "x.status='Completed'"
        matching = frappe.db.sql("""
            SELECT DISTINCT p.design_code
            FROM `tabDesign Milestone Plan Entry` p
            INNER JOIN `tabDesign Milestone Execution` x
              ON x.name=p.activated_execution AND x.design_code=p.design_code
            WHERE p.milestone_type=%s AND p.plan_state=%s
              AND """ + status_clause + """
            LIMIT %s
        """, (dashboard_milestone, "Active" if active else "Completed",
              MAX_CUSTODY_DESIGNS + 1), as_dict=True)
        if len(matching) > MAX_CUSTODY_DESIGNS:
            frappe.throw("Too many matching milestones. Narrow the selection.")
        names = {row.design_code for row in matching}
        # Keep the dashboard's own Current Milestone filter when a user
        # drills into a different bar (especially a Completed bar).
        if current_milestone and names:
            current = frappe.db.sql("""
                SELECT DISTINCT p.design_code
                FROM `tabDesign Milestone Plan Entry` p
                WHERE p.plan_state='Active' AND p.milestone_type=%s
                  AND p.design_code IN %s
            """, (current_milestone, tuple(sorted(names))), as_dict=True)
            names &= {row.design_code for row in current}
        # Dashboard deadline filter is a distinct-design condition, not
        # necessarily the same active milestone that was clicked.
        if deadline_status:
            if deadline_status not in ("Delayed", "On Track"):
                frappe.throw("Invalid deadline filter")
            from frappe.utils import today as current_day
            overdue = frappe.db.sql("""
                SELECT DISTINCT p.design_code
                FROM `tabDesign Milestone Plan Entry` p
                INNER JOIN `tabDesign Milestone Execution` x
                  ON x.name=p.activated_execution AND x.design_code=p.design_code
                WHERE p.plan_state='Active' AND x.status!='Completed'
                  AND x.due_date < %s
                  AND p.design_code IN %s
            """, (current_day(), tuple(sorted(names)) or ("",)), as_dict=True)
            delayed = {row.design_code for row in overdue}
            names = names & delayed if deadline_status == "Delayed" else names - delayed
        if "name" in filters:
            names &= set(filters["name"][1])
        if not names:
            return {"designs": [], "page": page,
                    "page_size": page_size, "has_more": False}
        filters["name"] = ["in", sorted(names)]
    search = (search or "").strip()
    if len(search) > 100:
        frappe.throw("Search must be 100 characters or less")
    options = {}
    if search:
        term = "%" + search + "%"
        options["or_filters"] = [
            ["Design Code", "name", "like", term],
            ["Design Code", "design_number", "like", term],
            ["Design Code", "mood_board", "like", term],
        ]
    # The Follow-Up Grid is a shared operational overview: authorized
    # Design Participants may view all Design Codes, not only designs in
    # their own assignments. The optional Designer/Custody filters remain
    # opt-in. This read-only scope does not authorize milestone actions.
    #
    # Users without the Design Participant role retain the normal
    # record-scoped Design Code query permissions.
    broad_grid_read = (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles(frappe.session.user)
        or "Marina Design Participant" in frappe.get_roles(frappe.session.user)
    )
    design_query = (frappe.get_list if dashboard_milestone else
                    frappe.get_all if broad_grid_read else frappe.get_list)
    designs = design_query("Design Code",
        filters=filters,
        fields=["name", "design_number", "image", "mood_board",
                "designer", "assigned_merchandiser", "development_stage",
                "creation_date", "creation"],
        order_by="modified desc, name desc",
        limit_start=(page - 1) * page_size,
        limit_page_length=page_size + 1,
        **options)
    has_more = len(designs) > page_size
    designs = designs[:page_size]
    if not designs:
        return {"designs": [], "page": page,
                "page_size": page_size, "has_more": False}
    ids = [row.name for row in designs]
    row_limit = len(ids) * MAX_PLANS_PER_DESIGN + 1
    plans = frappe.get_all("Design Milestone Plan Entry",
        filters={"design_code": ["in", ids]},
        fields=["name", "design_code", "milestone_type", "sequence",
                "plan_state", "depends_on_type", "trigger_status",
                "workflow_snapshot_json", "baseline_due_date", "completion_weight_days"],
        order_by="design_code asc, sequence asc, name asc",
        limit_page_length=row_limit)
    if len(plans) >= row_limit:
        frappe.throw("Too many milestone plans on the selected page")
    executions = frappe.get_all("Design Milestone Execution",
        filters={"design_code": ["in", ids]},
        fields=["name", "design_code", "plan_entry", "status",
                "current_custodian", "current_role",
                "latest_note", "due_date", "evidence_document", "evidence_file",
                "step_entered_on", "rework_count", "completed_on"],
        limit_page_length=row_limit)
    if len(executions) >= row_limit:
        frappe.throw("Too many milestone executions on the selected page")
    grouped = _allowed_rows(designs, plans, executions)
    # One permission-scoped batch avoids N+1 document title lookups.
    evidence_ids = sorted({e.evidence_document for e in executions
                           if e.evidence_document})
    evidence_metadata = {}
    if evidence_ids and frappe.has_permission("Design Document", "read"):
        docs = frappe.get_list("Design Document",
            filters={"name": ["in", evidence_ids]},
            fields=["name", "document_title", "attachment"],
            limit_page_length=len(evidence_ids))
        evidence_metadata = {doc.name: doc for doc in docs}
    # Projected Due is a rolling forecast; the original creation-based
    # baseline remains available internally for later variance reporting.
    # For intermediate trigger dates only, fetch one bounded event batch.
    from marina_custom_apps.design_management.clean_milestones.service import _rolling_events
    step_events = _rolling_events(plans, executions)
    execution_map = {row.plan_entry: row for row in executions}
    plan_groups = {name: [] for name in ids}
    for plan in plans:
        plan_groups[plan.design_code].append(plan)
    progress_by_design = {}
    for design in designs:
        selected_plans = plan_groups[design.name]
        origin = design.creation_date or design.creation
        baseline = projected_dates(selected_plans, origin)
        # Stored date takes priority. Legacy plans without that column's
        # value derive it from the immutable plan snapshot, never from live
        # operational due dates or changed Milestone Masters.
        progress_by_design[design.name] = baseline_progress(
            selected_plans, origin, execution_map, baseline)
        dates = rolling_projected_dates(
            selected_plans, origin, execution_map, step_events)
        for plan, row in zip(selected_plans, grouped[design.name]):
            row.update(dates[plan.name])
            row["baseline_due_date"] = (
                str(plan.baseline_due_date)[:10]
                if plan.baseline_due_date else
                baseline[plan.name]["projected_due_date"]
            )
            evidence = evidence_metadata.get(row["evidence_document"])
            row["evidence_title"] = (evidence.document_title or evidence.name) if evidence else None
            # The workflow pins the exact per-Design evidence file at the time
            # of milestone completion. Multi-designer Tech Packs have no single
            # primary attachment; never substitute another Designer's file.
            # Keep the primary attachment fallback for historical records only.
            execution = execution_map.get(plan.name)
            attachment = (execution.evidence_file if execution and execution.evidence_file
                          else evidence.attachment if evidence else None)
            # Never expose a file path for evidence the user cannot read.
            row["evidence_download_url"] = (
                attachment if evidence and isinstance(attachment, str) and
                attachment.startswith(("/files/", "/private/files/")) and
                ".." not in attachment and "?" not in attachment and
                "#" not in attachment else None
            )
            row["evidence_accessible"] = bool(evidence)
    user_ids = {row.designer for row in designs if row.designer}
    for exe in executions:
        if exe.current_custodian:
            user_ids.add(exe.current_custodian)
    names = {}
    if user_ids:
        users = frappe.get_all("User", filters={"name": ["in", sorted(user_ids)]},
            fields=["name", "username"],
            limit_page_length=len(user_ids))
        # Always show User.username, never full_name or the stored email ID.
        # Keep the ID as the internal grouping/permission key.
        names = {u.name: ((u.username or "").strip() or "Username not configured")
                 for u in users}
    result = []
    for doc in designs:
        result.append({"name": doc.name, "design_number": doc.design_number,
            "image": doc.image, "mood_board": doc.mood_board,
            "designer": names.get(
                doc.designer,
                "Username not configured" if doc.designer else ""),
            "development_stage": doc.development_stage,
            "completion_percent": progress_by_design[doc.name]["percent"],
            "baseline_earned_days": progress_by_design[doc.name]["earned_days"],
            "baseline_total_days": progress_by_design[doc.name]["total_days"],
            "milestones": [{**r, "custodian_title":
                            names.get(r["current_custodian"],
                                      "Username not configured" if r["current_custodian"] else "")}
                           for r in grouped[doc.name]]})
    return {"designs": result, "page": page, "page_size": page_size,
            "has_more": has_more, "as_of": today()}


@frappe.whitelist(methods=["POST"])
def save_grid_notes(changes):
    """Save at most 50 edited notes with custody authority and audit history."""
    from marina_custom_apps.design_management.clean_milestones.service import (
        _authorize, _design, _event, _lock_design,
    )
    if isinstance(changes, str):
        changes = frappe.parse_json(changes)
    if not isinstance(changes, list) or not 1 <= len(changes) <= 50:
        frappe.throw("Submit between 1 and 50 note edits")
    validated, keys = [], set()
    for row in changes:
        if not isinstance(row, dict):
            frappe.throw("Invalid note payload")
        design_code = row.get("design_code")
        execution_name = row.get("execution")
        note = row.get("note")
        expected = row.get("expected_note")
        if (not isinstance(design_code, str) or not design_code or
                not isinstance(execution_name, str) or not execution_name or
                not isinstance(note, str) or not (1 <= len(note.strip()) <= 500)
                or not isinstance(expected, str)):
            frappe.throw("Each note needs its current value and 1–500 new characters")
        key = (design_code, execution_name)
        if key in keys:
            frappe.throw("Duplicate milestone note")
        keys.add(key)
        validated.append((design_code, execution_name, note.strip(), expected))
    documents = {}
    for name in sorted({row[0] for row in validated}):
        documents[name] = _design(name)
        _lock_design(name)
    rows = frappe.get_all("Design Milestone Execution",
        filters={"name": ["in", [row[1] for row in validated]]},
        fields=["name", "design_code", "plan_entry", "status",
                "current_role", "current_custodian", "latest_note"],
        limit_page_length=len(validated))
    found = {row.name: row for row in rows}
    for design_code, execution_name, note, expected in validated:
        row = found.get(execution_name)
        if not row or row.design_code != design_code:
            frappe.throw("Milestone not part of this Design", frappe.PermissionError)
        if row.status == "Completed":
            frappe.throw("Completed milestone notes are immutable")
        if (row.latest_note or "") != expected:
            frappe.throw("Note changed by another user. Refresh the grid before saving.")
        _authorize(frappe.session.user, "Advance Milestone Step",
                   documents[design_code], row.current_role, note)
    saved = 0
    for design_code, execution_name, note, expected in validated:
        row = found[execution_name]
        if (row.latest_note or "") == note:
            continue
        frappe.db.set_value("Design Milestone Execution", execution_name,
            {"latest_note": note, "last_action_on": now_datetime()},
            update_modified=False)
        # No status or custodian change, but retain an immutable event entry.
        _event(documents[design_code], frappe._dict({"name": row.plan_entry}),
               row, "Note Updated", old=row.status,
               prior=row.current_custodian, reason=note)
        saved += 1
    return {"saved": saved}

