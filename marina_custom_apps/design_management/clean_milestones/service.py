"""Clean Release 22 milestone service with one event-triggered state machine.

All writes happen in the same Frappe request transaction; never commit here.
Design row locking serializes manual step transitions + automatic activations.
"""
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import frappe
from frappe.utils import now_datetime, getdate, get_datetime, today

from marina_custom_apps.design_management.clean_milestones.rules import (
    ConfigurationError, configured_steps, validate_master_definition,
    allowed_next, trigger_matches,
)
from marina_custom_apps.design_management.clean_milestones.return_rules import trigger_reached
from marina_custom_apps.design_management.clean_milestones.schedule import rolling_projected_dates
from marina_custom_apps.design_management.security.organization import (
    can_manage_role, user_roles, role_catalog,
)
from marina_custom_apps.design_management.security.role_access import can_action, enabled

MAX_SELECTED = 50


def _lock_design(name):
    if not frappe.db.sql(
            "SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
            (name,)):
        frappe.throw("Design Code not found")


def _design(name):
    # Reading milestones does not require optional module RBAC enforcement.
    # Native Design Code read permission remains mandatory.
    design = frappe.get_doc("Design Code", name)
    design.check_permission("read")
    return design


def _is_admin(actor):
    return actor == "Administrator" or "System Manager" in frappe.get_roles(actor)


def _role_user(design, role):
    from marina_custom_apps.design_management.security.participants import is_participant
    if not role or role not in role_catalog():
        frappe.throw("Step uses an invalid or inactive Module Role")
    assigned = [r.user for r in (design.get("r22_team_assignments") or [])
                if r.active and r.module_role == role]
    if len(assigned) != 1:
        frappe.throw("Assign exactly one active " + role +
                     " employee in the Design Team before scheduling")
    user = assigned[0]
    if (role not in user_roles(user) or
            not is_participant(user)):
        frappe.throw("Assigned " + role +
                     " employee must be active and hold the Marina Design Participant role")
    return user


def _authorize(actor, action, design, role=None, reason=None, custodian=None):
    from marina_custom_apps.design_management.security.user_permissions import configured
    individualized = configured(actor)
    # Preserve legacy native-admin behavior only for non-configured users.
    if _is_admin(actor) and not individualized:
        return
    owner = _role_user(design, role) if role else None
    if not can_action(action, actor, custodian=custodian if custodian is not None else owner):
        frappe.throw("Missing Design Action: " + action, frappe.PermissionError)
    # Individual permissions replace hierarchy authorization, not milestone
    # sequencing, mandatory evidence or eligible-custodian validations.
    if individualized:
        return
    if role:
        if actor == owner and role in user_roles(actor):
            return
        if (can_manage_role(actor, role) and len((reason or "").strip()) >= 5):
            return
        frappe.throw("Only the assigned " + role +
                     " employee or authorized team manager may perform this step",
                     frappe.PermissionError)


def _event(design, plan, execution, action, old=None, prior=None,
           actor=None, reason=None, evidence=None, evidence_file=None, effective_date=None):
    event = frappe.get_doc({
        "doctype": "Design Milestone Custody Event",
        "name": uuid4().hex, "request_id": uuid4().hex,
        "design_code": design.name, "plan_entry": plan.name,
        "execution": execution.name, "action": action,
        "from_status": old, "to_status": execution.status,
        "from_user": prior, "to_user": execution.current_custodian,
        "performed_by": actor or frappe.session.user,
        "performed_on": now_datetime(), "reason": reason or "",
        "effective_date": getdate(effective_date) if effective_date else None,
        "evidence_document": evidence,
        "evidence_file": evidence_file,
    })
    event.db_insert()
    return event.name


def _snapshots(names):
    docs = [frappe.get_doc("Design Milestone Type", name) for name in names]
    selected = set(names)
    items = []
    for doc in docs:
        if not doc.is_active:
            frappe.throw("Inactive Milestone: " + doc.name)
        snapshot = {
            "name": doc.name, "sequence": int(doc.sequence or 0),
            "start_with_design_creation": bool(doc.start_with_design_creation),
            "depends_on_type": doc.depends_on_type or None,
            "trigger_status": doc.r22_trigger_status or "Completed",
            "steps": [r.as_dict() for r in (doc.get("workflow_steps") or [])],
            "completion_weight_days": int(doc.completion_weight_days or 0),
        }
        try:
            validate_master_definition(snapshot)
        except ConfigurationError as exc:
            frappe.throw(str(exc))
        if snapshot["depends_on_type"] and snapshot["depends_on_type"] not in selected:
            frappe.throw("Select predecessor " + snapshot["depends_on_type"] +
                         " for " + doc.name)
        items.append(snapshot)
    by_name = {r["name"]: r for r in items}
    visited, visiting = set(), set()

    def visit(name):
        if name in visiting:
            frappe.throw("Circular milestone trigger configuration")
        if name in visited:
            return
        visiting.add(name)
        prev = by_name[name]["depends_on_type"]
        if prev:
            visit(prev)
            available = {x["step"] for x in configured_steps(by_name[prev]["steps"])}
            if by_name[name]["trigger_status"] not in available:
                frappe.throw("Predecessor " + prev + " does not contain step " +
                             by_name[name]["trigger_status"])
        visiting.remove(name)
        visited.add(name)

    for row in items:
        visit(row["name"])
    items.sort(key=lambda x: (x["sequence"], x["name"]))
    return items


def _target_date(entered, snapshot, current):
    """Projected due date based only on remaining step lead days."""
    stages = configured_steps(snapshot["steps"])
    normal = [r for r in stages if r["step"] != "Rework"]
    names = [r["step"] for r in normal]
    if current not in names or current == "Completed":
        return None
    following = normal[names.index(current) + 1:]
    lead = sum(s["lead_time_days"] for s in following)
    return (getdate(entered) + timedelta(days=lead)).isoformat() if lead else None


def tech_pack_exemption_applies(design, milestone_snapshot, first_step):
    """Only waive Tech Pack evidence for an explicitly opted-out Design Code.

    Other milestone evidence types (Fitting, QC, Shipping, etc.) stay mandatory.
    A Tech Pack is a document type, not an inferred milestone title.
    """
    evidence_type = str(first_step.get("evidence_type") or "").strip().casefold()
    return bool(
        design.get("tech_pack_not_required")
        and first_step.get("requires_evidence")
        and evidence_type in {"tech pack", "technical pack", "techpack"}
        and first_step.get("step") == "Completed"
        and first_step.get("transition_mode") == "Auto"
        and len(configured_steps(milestone_snapshot["steps"])) == 1
    )


def _activate(design, trigger_name=None, trigger_step=None, trigger_steps=None,
              trigger_sequence=None, effective_moment=None):
    plans = frappe.get_all("Design Milestone Plan Entry",
        filters={"design_code": design.name, "plan_state": "Planned"},
        fields=["*"], order_by="sequence asc, name asc", limit_page_length=MAX_SELECTED+1)
    if len(plans) > MAX_SELECTED:
        frappe.throw("Too many milestone plan rows")
    activated = []
    for plan in plans:
        cfg = json.loads(plan.workflow_snapshot_json)
        if cfg["start_with_design_creation"]:
            if trigger_name is not None and not (
                    plan.activated_execution and trigger_step == "Completed"
                    and trigger_sequence is not None
                    and int(plan.sequence or 0) > int(trigger_sequence or 0)):
                # Initially independent stages still start together at plan
                # creation. Only already executed stages that were pushed to
                # Future by a return can restart at the earlier frontier.
                continue
        elif plan.depends_on_type != trigger_name or not (
                trigger_matches(plan.depends_on_type, plan.trigger_status,
                                trigger_name, trigger_step)
                or (trigger_steps and trigger_reached(
                    trigger_steps, plan.trigger_status, trigger_step))):
            continue
        steps = configured_steps(cfg["steps"])
        first = steps[0]
        auto_completed = (
            len(steps) == 1 and first["step"] == "Completed"
            and first["transition_mode"] == "Auto"
        )
        evidence = None
        evidence_file = None
        if auto_completed:
            # A one-step Completed milestone is a factual acknowledgement
            # of already-released work, NOT a shortcut around evidence.
            if not first["requires_evidence"]:
                frappe.throw("An Auto Completed milestone requires Published evidence")
            exempt = tech_pack_exemption_applies(design, cfg, first)
            if not exempt:
                from marina_custom_apps.design_management.clean_milestones.evidence import (
                    matching_published_documents, evidence_document_details,
                )
                documents = matching_published_documents(
                    design.name, plan.milestone_type, first["evidence_type"])
                if len(documents) != 1:
                    frappe.throw(
                        "One Published Design Document must be linked to " +
                        design.name + " / " + plan.milestone_type +
                        " before initializing this one-step Completed milestone"
                    )
                # Recheck under a document lock so an in-flight Unpublish or
                # assignment removal cannot invalidate the evidence.
                frappe.db.sql(
                    "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
                    (documents[0].name,),
                )
                verified, linked = evidence_document_details(
                    design.name, plan.milestone_type, documents[0].name,
                    first["evidence_type"])
                if not linked:
                    if (verified.document_type == "Tech Pack"
                            and verified.tech_pack_mood_board):
                        from marina_custom_apps.design_management.clean_milestones.evidence import _bind_to_milestone
                        _bind_to_milestone(verified, design.name, plan.milestone_type,
                                           first["evidence_type"])
                    else:
                        frappe.throw("Published evidence assignment changed during initialization")
                evidence = verified.name
                from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import designer_file
                evidence_file = (designer_file(verified, design)
                                 if verified.document_type == "Tech Pack" and verified.tech_pack_mood_board
                                 else verified.attachment)
        owner = _role_user(design, first["custody_role"])
        time = effective_moment or now_datetime()
        # On a controlled return, retain the original execution identity:
        # custody history contains Link references to this execution.
        stored = frappe.db.get_value(
            "Design Milestone Execution", {"plan_entry": plan.name}, "name")
        if stored and stored != plan.activated_execution:
            frappe.throw("Existing execution does not match milestone plan")
        if not stored and plan.activated_execution:
            frappe.throw("Milestone execution was removed unexpectedly")
        values = {
            "status": first["step"],
            "current_role": first["custody_role"],
            "current_custodian": owner,
            "step_entered_on": time,
            "due_date": (getdate(time).isoformat() if auto_completed else
                         _target_date(time, cfg, first["step"])),
            # The effective start may be backdated to the Design planning
            # baseline. Audit/system action time must remain the real time.
            "rework_count": 0, "last_action_on": now_datetime(),
            "completed_by": frappe.session.user if auto_completed else None,
            "completed_on": time if auto_completed else None,
            "evidence_document": evidence, "evidence_file": evidence_file,
            "latest_note": None,
        }
        if stored:
            frappe.db.set_value("Design Milestone Execution", stored, values,
                                update_modified=False)
            execution = frappe._dict(
                name=stored, status=first["step"], current_custodian=owner)
        else:
            execution = frappe.get_doc({
                "doctype": "Design Milestone Execution", "name": uuid4().hex,
                "design_code": design.name, "plan_entry": plan.name,
                "milestone_type": plan.milestone_type, **values,
            })
            execution.db_insert()
        frappe.db.set_value("Design Milestone Plan Entry", plan.name, {
            "plan_state": "Completed" if auto_completed else "Active",
            "activated_execution": execution.name,
        }, update_modified=False)
        _event(design, plan, execution,
               ("Auto Completed" if auto_completed else
                "Auto Reactivated" if stored else "Auto Activated"),
               old="Planned" if stored else None,
               evidence=evidence, evidence_file=evidence_file,
               effective_date=time)
        activated.append(plan.milestone_type)
        if auto_completed:
            # Propagate the newly completed event to dependents, including
            # a milestone initialized in the same create_plan transaction.
            activated.extend(_activate(
                design, plan.milestone_type, "Completed",
                steps, plan.sequence, effective_moment=time))
    return activated


def _require_all_active_milestones(names):
    """Reject omitted or stale milestones before creating any plan rows.

    Both individual and bulk creation pass here. Return the canonical master
    order, while existing plans retain their saved snapshots unchanged.
    """
    active = frappe.get_all("Design Milestone Type",
        filters={"is_active": 1}, pluck="name",
        order_by="sequence asc, name asc", limit_page_length=MAX_SELECTED + 1)
    if not active or len(active) > MAX_SELECTED:
        frappe.throw("Configure between 1 and 50 active Milestone Types")
    if set(names) != set(active):
        frappe.throw(
            "All active milestones are required. Milestone configuration may have "
            "changed; close and reopen Create Milestones, or refresh the bulk preview.")
    return active


def create_plan(design_code, milestone_types, lead_time_overrides=None):
    """Initialize a Design-specific frozen plan using optional custom durations."""
    design = _design(design_code)
    actor = frappe.session.user
    _authorize(actor, "Assign Milestones", design)
    if isinstance(milestone_types, str):
        milestone_types = frappe.parse_json(milestone_types)
    if not isinstance(milestone_types, list) or not milestone_types:
        frappe.throw("All active milestones are required to create a plan")
    if any(not isinstance(name, str) or not name for name in milestone_types):
        frappe.throw("Milestone names must be nonempty strings")
    if len(milestone_types) > MAX_SELECTED or len(milestone_types) != len(set(milestone_types)):
        frappe.throw("Select unique milestones (maximum 50)")
    _lock_design(design_code)
    # The exemption is editable only before planning. Refresh it after the
    # row lock so concurrent saves cannot change what this plan records.
    design.tech_pack_not_required = frappe.db.get_value(
        "Design Code", design_code, "tech_pack_not_required"
    )
    milestone_types = _require_all_active_milestones(milestone_types)
    # Re-read the planning baseline *after* locking. A Design Code edit may
    # have changed it between the initial _design read and this transaction.
    baseline_date = frappe.db.get_value("Design Code", design_code, "creation_date")
    if not baseline_date:
        frappe.throw("Set a Creation Date before creating milestones")
    if getdate(baseline_date) > getdate(today()):
        frappe.throw("Creation Date cannot be in the future")
    design.creation_date = baseline_date
    # Draft Designs may omit artwork, but initializing milestones requires it.
    if not frappe.db.get_value("Design Code", design_code, "image"):
        frappe.throw("Attach Main Image to the Design Code before creating milestones")
    if frappe.db.exists("Design Milestone Plan Entry", {"design_code": design_code}):
        frappe.throw("A milestone plan already exists for this Design")
    # Keep draft creation flexible, but the first milestone needs a real,
    # eligible designer. The stored compatibility field is not authority:
    # resolve the active Designer row from the Team Assignments snapshot.
    if not any(r.active and r.module_role == "Designer" and r.user
               for r in (design.get("r22_team_assignments") or [])):
        frappe.throw("Assign a Designer in Team Assignments before creating milestones")
    _role_user(design, "Designer")
    snapshots = _snapshots(milestone_types)
    if lead_time_overrides is None:
        lead_time_overrides = {}
    if isinstance(lead_time_overrides, str):
        lead_time_overrides = frappe.parse_json(lead_time_overrides)
    from marina_custom_apps.design_management.clean_milestones.planning_overrides import (
        apply_duration_overrides,
    )
    try:
        snapshots = apply_duration_overrides(snapshots, lead_time_overrides)
    except ValueError as exc:
        frappe.throw(str(exc))
    # Fail before writing: every role used anywhere must resolve to a person.
    for snapshot in snapshots:
        for stage in configured_steps(snapshot["steps"]):
            for role in (stage["custody_role"], stage["responsible_module_role"]):
                if role:
                    _role_user(design, role)
    # Freeze each milestone's original completion baseline ONCE, using
    # the Design Code creation date and its per-Design duration overrides.
    # It is deliberately separate from rolling_projected_dates / due_date.
    from marina_custom_apps.design_management.clean_milestones.schedule import projected_dates
    initial_plan_rows = [
        frappe._dict(
            name=cfg["name"],
            milestone_type=cfg["name"],
            depends_on_type=cfg["depends_on_type"],
            trigger_status=cfg["trigger_status"],
            workflow_snapshot_json=json.dumps(cfg, sort_keys=True, default=str),
        ) for cfg in snapshots
    ]
    frozen_dates = projected_dates(initial_plan_rows, baseline_date)
    from marina_custom_apps.design_management.clean_milestones.schedule import milestone_weight_days
    for cfg in snapshots:
        identifier = hashlib.sha256(
            (design_code + "\0" + cfg["name"]).encode()).hexdigest()
        frappe.get_doc({
            "doctype": "Design Milestone Plan Entry", "name": uuid4().hex,
            "plan_key": identifier, "design_code": design_code,
            "milestone_type": cfg["name"], "sequence": cfg["sequence"],
            "depends_on_type": cfg["depends_on_type"],
            "trigger_status": cfg["trigger_status"],
            "plan_state": "Planned",
            "workflow_snapshot_json": json.dumps(cfg, sort_keys=True, default=str),
            "baseline_due_date": frozen_dates[cfg["name"]]["projected_due_date"],
            "completion_weight_days": milestone_weight_days(cfg),
            "selected_on": now_datetime(), "selected_by": actor,
        }).db_insert()
    # All milestones configured Start with Design Creation begin on the
    # selected Creation Date, not when the user clicks Create Plan.
    # Auto-completed Tech Pack evidence receives that effective date while
    # real performed_on audit timestamps remain now_datetime().
    start_moment = get_datetime(str(getdate(baseline_date)) + " 00:00:00")
    activated = _activate(design, effective_moment=start_moment)
    return {"planned": len(snapshots), "activated": activated}


def _next_allowed(snapshot, old):
    stages = configured_steps(snapshot["steps"])
    return [x for x in stages
            if x["transition_mode"] == "Manual"
            and allowed_next(stages, old, x["step"])]


def advance(design_code, execution_name, next_step, reason=None,
            evidence_document=None, confirm_evidence_link=False,
            step_change_date=None):
    """User-selected manual step; custody changes to target step's designated role."""
    design = _design(design_code)
    actor = frappe.session.user
    _lock_design(design_code)
    row = frappe.db.get_value("Design Milestone Execution", execution_name,
                              "*", as_dict=True)
    if not row or row.design_code != design_code:
        frappe.throw("Execution does not belong to this Design")
    plan = frappe.db.get_value("Design Milestone Plan Entry", row.plan_entry,
                               "*", as_dict=True)
    if (not plan or plan.design_code != design_code or
            plan.activated_execution != row.name or plan.plan_state != "Active"):
        frappe.throw("Plan/execution mismatch or milestone is not Active")
    if row.status == next_step:
        return {"unchanged": True, "status": row.status}
    snapshot = json.loads(plan.workflow_snapshot_json)
    eligible = {x["step"]: x for x in _next_allowed(snapshot, row.status)}
    if next_step not in eligible:
        frappe.throw("Step transition is not permitted at this point")
    stage = eligible[next_step]
    _authorize(actor, "Advance Milestone Step", design,
               stage["responsible_module_role"], reason,
               custodian=row.current_custodian)
    recorded_at = now_datetime()  # Real timestamp of user's action.
    if step_change_date is None or step_change_date == "":
        effective_day = getdate(recorded_at)
    else:
        if not isinstance(step_change_date, str):
            frappe.throw("Step Change Date must be a YYYY-MM-DD date")
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", step_change_date):
            frappe.throw("Step Change Date must be a YYYY-MM-DD date")
        try:
            effective_day = getdate(step_change_date)
        except (TypeError, ValueError):
            frappe.throw("Invalid Step Change Date")
    if effective_day > getdate(recorded_at):
        frappe.throw("Step Change Date cannot be in the future")
    first_allowed_day = getdate(row.step_entered_on or
                               design.creation_date or design.creation)
    if effective_day < first_allowed_day:
        frappe.throw("Step Change Date cannot precede the current step's start date")
    # Backdated operational step date, but actual audit timestamps remain now.
    moment = recorded_at.replace(year=effective_day.year,
                                 month=effective_day.month, day=effective_day.day)
    if next_step == "Rework" and len((reason or "").strip()) < 5:
        frappe.throw("Enter a rejection / rework reason")
    if row.status == "Rework" and next_step == "Completed" and len(
            (reason or "").strip()) < 5:
        frappe.throw("Explain corrections before confirming completion")
    if next_step == "Completed" and row.milestone_type == "Shipment Ready":
        if frappe.db.get_value("Design Milestone Plan Entry", {
                "design_code": design_code, "milestone_type": "Bulk Production"},
                "plan_state") != "Completed":
            frappe.throw("Bulk Production must be Completed before shipment readiness is confirmed")
    # Validate next custody BEFORE binding evidence; any later failure still
    # rolls back both assignment and milestone in the request transaction.
    next_custodian = _role_user(design, stage["custody_role"])
    chosen_document = None
    if stage["requires_evidence"]:
        from marina_custom_apps.design_management.clean_milestones.evidence import required_document
        chosen_document = required_document(
            design_code, row.milestone_type, stage["evidence_type"],
            evidence_document, confirm_link=str(confirm_evidence_link).lower()
            in ("1", "true"))
    from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import designer_file
    chosen_file = None
    if chosen_document:
        chosen_doc = frappe.get_doc("Design Document", chosen_document)
        chosen_file = (designer_file(chosen_doc, design)
                       if chosen_doc.document_type == "Tech Pack" and chosen_doc.tech_pack_mood_board
                       else chosen_doc.attachment)
    old_step, old_custodian = row.status, row.current_custodian
    if next_step == "Completed" and not row.due_date:
        # Freeze the last displayed forecast on completion, including a
        # zero-day step. The existing due_date field is the historical
        # comparison point; no additional database field/query is needed.
        normal_steps = [x["step"] for x in configured_steps(snapshot["steps"])
                        if x["step"] != "Rework"]
        if old_step in normal_steps and row.step_entered_on:
            row.due_date = (
                _target_date(row.step_entered_on, snapshot, old_step) or
                getdate(row.step_entered_on).isoformat()
            )
    update = {
        "status": next_step, "current_role": stage["custody_role"],
        "current_custodian": next_custodian,
        "step_entered_on": moment, "last_action_on": recorded_at,
        # Retain the operational deadline when work finishes; clearing it
        # would hide planned-vs-actual deadline comparisons in reports.
        "due_date": (row.due_date if next_step == "Completed" else
                     _target_date(moment, snapshot, next_step)),
        "evidence_document": chosen_document or row.evidence_document,
        "evidence_file": chosen_file or row.evidence_file,
    }
    if (reason or "").strip():
        update["latest_note"] = reason.strip()[:500]
    if next_step == "Rework":
        update["rework_count"] = int(row.rework_count or 0) + 1
    if next_step == "Completed":
        update.update({"completed_by": actor, "completed_on": moment})
    frappe.db.set_value("Design Milestone Execution", row.name, update,
                        update_modified=False)
    row.update(update)
    if next_step == "Completed":
        frappe.db.set_value("Design Milestone Plan Entry", plan.name,
                            "plan_state", "Completed", update_modified=False)
    event_id = _event(design, plan, row, "Step " + next_step,
           old=old_step, prior=old_custodian,
           actor=actor, reason=reason, evidence=chosen_document,
           evidence_file=chosen_file, effective_date=effective_day)
    triggered = _activate(design, row.milestone_type, next_step,
                          configured_steps(snapshot["steps"]), plan.sequence,
                          effective_moment=moment)
    if next_step == "Completed":
        from marina_custom_apps.design_management.discussion_activity import milestone_completed
        milestone_completed(design, row, event_id, triggered, effective_day)
    return {"status": next_step, "custodian": next_custodian,
            "activated": triggered}


def _rolling_events(plans, executions):
    """Read only intermediate-trigger events relevant to future milestones.

    One bounded, scoped batch retrieves step dates that execution.current
    no longer contains. We never scan a complete audit history per milestone.
    """
    by_plan = {row.plan_entry: row for row in executions}
    by_type = {row.milestone_type: row for row in plans}
    needed = set()
    for child in plans:
        if child.plan_state != "Planned" or not child.depends_on_type:
            continue
        if child.trigger_status in ("Completed", "Rework"):
            continue
        parent = by_type.get(child.depends_on_type)
        exe = by_plan.get(parent.name) if parent else None
        if parent and exe and exe.status != child.trigger_status:
            needed.add(parent.name)
    if not needed:
        return {}
    capacity = min(5000, len(needed) * 30)
    rows = frappe.get_all(
        "Design Milestone Custody Event",
        filters={"plan_entry": ["in", sorted(needed)]},
        fields=["name", "plan_entry", "action", "to_status",
                "effective_date", "performed_on"],
        order_by="performed_on desc, name desc",
        limit_page_length=capacity + 1,
    )
    if len(rows) > capacity:
        frappe.throw("Milestone audit history exceeds rolling forecast limit")
    events = {name: [] for name in needed}
    for event in rows:
        events[event.plan_entry].append(event)
    return events


def overview(design_code):
    from marina_custom_apps.design_management.security.user_permissions import configured
    design = _design(design_code)
    plans = frappe.get_all("Design Milestone Plan Entry",
        filters={"design_code": design_code},
        fields=["name", "milestone_type", "sequence", "plan_state",
                "depends_on_type", "trigger_status", "activated_execution",
                "workflow_snapshot_json"], order_by="sequence asc, name asc",
        limit_page_length=MAX_SELECTED+1)
    executions = frappe.get_all("Design Milestone Execution",
        filters={"design_code": design_code},
        fields=["name", "plan_entry", "milestone_type", "status",
                "current_custodian", "current_role", "due_date", "rework_count",
                "evidence_document", "step_entered_on", "completed_on"], limit_page_length=MAX_SELECTED+1)
    by_plan = {e.plan_entry: e for e in executions}
    rolling = rolling_projected_dates(
        plans, design.creation_date or design.creation,
        {e.plan_entry: e for e in executions},
        _rolling_events(plans, executions))
    actor = frappe.session.user
    from marina_custom_apps.design_management.api.user_display import usernames_for_user_ids
    titles = usernames_for_user_ids(
        (e.current_custodian for e in executions if e.current_custodian),
        max_users=MAX_SELECTED + 1)
    visible = []
    for plan in plans:
        cfg = json.loads(plan.workflow_snapshot_json)
        exe = by_plan.get(plan.name)
        row = {
            "milestone_type": plan.milestone_type,
            "state": plan.plan_state,
            "trigger_milestone": plan.depends_on_type,
            "trigger_step": plan.trigger_status,
            **rolling.get(plan.name, {}),
            "completion_date": None,
        }
        if exe and plan.plan_state != "Planned":
            row.update({
                "execution": exe.name, "status": exe.status,
                "current_custodian": exe.current_custodian,
                "current_custodian_username": (titles.get(
                    exe.current_custodian, "Username not configured")
                    if exe.current_custodian else ""),
                "custody_role": exe.current_role,
                "due_date": exe.due_date,
                "completion_date": (
                    str(exe.completed_on)[:10]
                    if plan.plan_state == "Completed" and exe.status == "Completed"
                    and exe.completed_on else None),
                "rework_count": exe.rework_count,
            })
            allowed = []
            evidence_types = {}
            for step in _next_allowed(cfg, exe.status):
                if (can_action("Advance Milestone Step", actor,
                               custodian=exe.current_custodian) if configured(actor)
                    else (_is_admin(actor) or (
                        can_action("Advance Milestone Step", actor) and
                        (actor == next(
                            (r.user for r in (design.get("r22_team_assignments") or [])
                             if r.active and r.module_role == step["responsible_module_role"]),
                            None) or can_manage_role(actor, step["responsible_module_role"]))))):
                    allowed.append(step["step"])
                    if step["requires_evidence"]:
                        evidence_types[step["step"]] = step["evidence_type"]
            row["allowed_steps"] = allowed
            row["evidence_types"] = evidence_types
        visible.append(row)
    return {"design_code": design_code,
            "current": [x for x in visible if x["state"] == "Active"],
            "completed": [x for x in visible if x["state"] == "Completed"],
            "future": [x for x in visible if x["state"] == "Planned"],
            "can_plan": bool(not plans and (
                can_action("Assign Milestones", actor) if configured(actor)
                else (_is_admin(actor) or can_action("Assign Milestones", actor)))),
            "requires_main_image": not bool(design.image)}


def history(design_code, offset=0, limit=50):
    """Read paginated custody events and batch-resolve milestone/user names.

    Design Milestone Custody Event stores plan_entry, not milestone_type.
    Keeping its audit schema normalized avoids duplicating mutable labels
    or requiring another database column/migration for the history view.
    """
    from marina_custom_apps.design_management.api.user_display import usernames_for_user_ids
    _design(design_code)
    events = frappe.get_all("Design Milestone Custody Event",
        filters={"design_code": design_code},
        fields=["plan_entry", "action", "from_status", "to_status",
                "from_user", "to_user", "performed_by", "performed_on",
                "effective_date", "reason", "evidence_document"],
        order_by="performed_on desc, name desc",
        limit_start=max(0,int(offset)), limit_page_length=min(100,max(1,int(limit))))
    if not events:
        return []
    ids = sorted({event.plan_entry for event in events if event.plan_entry})
    names = {}
    if ids:
        plans = frappe.get_all("Design Milestone Plan Entry",
            filters={"design_code": design_code, "name": ["in", ids]},
            fields=["name", "milestone_type"], limit_page_length=len(ids))
        names = {plan.name: plan.milestone_type for plan in plans}
    titles = usernames_for_user_ids(
        (u for e in events for u in (e.from_user, e.to_user, e.performed_by) if u),
        max_users=300)
    for event in events:
        event["milestone_type"] = names.get(event.plan_entry, "")
        event["performed_by_username"] = titles.get(
            event.performed_by, "Username not configured")
        event["from_user_username"] = titles.get(
            event.from_user, "Username not configured") if event.from_user else ""
        event["to_user_username"] = titles.get(
            event.to_user, "Username not configured") if event.to_user else ""
        del event["plan_entry"]
    return events
