"""Baseline milestone schedule from frozen Release 22 plan snapshots.

This is a READ-ONLY projection for reporting. It never updates execution
due_date, changes custody/status or reruns milestone triggers.

Baseline = Design Code creation_date (fallback: document creation timestamp).
For each milestone, finish = projected trigger/start date + enabled NORMAL
step lead times *after* the initial step. Each lead_time_days belongs to the
step being reached (not to the step being left), matching service._target_date.
Parallel branches have independent dates; Rework is unpredictable and excluded.
"""
import json
from datetime import date, timedelta

from marina_custom_apps.design_management.clean_milestones.rules import configured_steps


def _field(row, name, default=None):
    return row.get(name, default) if isinstance(row, dict) else getattr(
        row, name, default)


def _baseline_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value.date() if hasattr(value, "date") else value
    return date.fromisoformat(str(value)[:10])


def _normal_steps(snapshot):
    return [step for step in configured_steps(snapshot["steps"])
            if step["step"] != "Rework"]


def _days_to_step(steps, step_name):
    """Days from activation to a configured, non-Rework milestone step."""
    positions = [s["step"] for s in steps]
    if step_name not in positions:
        return None
    index = positions.index(step_name)
    return sum(s["lead_time_days"] for s in steps[1:index + 1])


def projected_dates(plans, creation_date):
    """Return {plan_name: {projected_start_date, projected_due_date}}.

    Uses only existing Design plans and their saved snapshot, not the mutable
    Milestone Master. A missing predecessor or non-deterministic trigger
    yields None for that milestone/its dependents, never invented dates.
    Calculations are O(milestones + configured steps) per Design.
    """
    baseline = _baseline_date(creation_date)
    entries = {}
    for plan in plans:
        snap = json.loads(_field(plan, "workflow_snapshot_json"))
        entries[_field(plan, "milestone_type")] = (plan, snap, _normal_steps(snap))

    cache = {}
    visiting = set()

    def evaluate(milestone):
        if milestone in cache:
            return cache[milestone]
        record = entries.get(milestone)
        if not record or milestone in visiting:
            return None
        visiting.add(milestone)
        plan, snap, steps = record
        start = None
        if baseline is not None:
            if snap.get("start_with_design_creation"):
                start = baseline
            else:
                dependency = snap.get("depends_on_type") or _field(
                    plan, "depends_on_type")
                predecessor = evaluate(dependency) if dependency else None
                if predecessor:
                    predecessor_steps = entries[dependency][2]
                    trigger = snap.get("trigger_status") or _field(
                        plan, "trigger_status") or "Completed"
                    offset = _days_to_step(predecessor_steps, trigger)
                    if offset is not None:
                        start = predecessor["projected_start"] + timedelta(
                            days=offset)
        due = start + timedelta(days=_days_to_step(steps, "Completed") or 0) \
            if start is not None else None
        result = {
            "projected_start": start, "projected_due": due,
            "projected_start_date": start.isoformat() if start else None,
            "projected_due_date": due.isoformat() if due else None,
        }
        visiting.remove(milestone)
        cache[milestone] = result
        return result

    result = {}
    for plan in plans:
        forecast = evaluate(_field(plan, "milestone_type"))
        result[_field(plan, "name")] = (
            {"projected_start_date": forecast["projected_start_date"],
             "projected_due_date": forecast["projected_due_date"]}
            if forecast else
            {"projected_start_date": None, "projected_due_date": None}
        )
    return result


def baseline_progress(plans, creation_date, executions=None, legacy_dates=None):
    """Stable timeline-weighted Design completion, independent of actual dates.

    Timeline = calendar days from frozen Design Creation Date to the latest
    initial projected due date. For parallel branches the maximum initial due
    is used rather than the last display-sequence date: this prevents a later
    displayed milestone with an earlier deadline from distorting the score.

    Credit advances only through the last CONSECUTIVELY completed milestone
    in display sequence. Rework/return automatically lowers the earned
    frontier without rewriting the saved baseline; a parallel completion
    beyond the frontier earns no premature credit.

    New plans use stored baseline_due_date. Historical plans, created before
    that field existed, derive the same fixed schedule from their immutable
    workflow_snapshot_json and the locked Design creation_date; never read
    or recalculate from operational due_date or Milestone Master.
    """
    entries = sorted(plans, key=lambda p: (
        int(_field(p, "sequence") or 0),
        str(_field(p, "milestone_type") or ""),
        str(_field(p, "name") or ""),
    ))
    if not entries:
        return {"percent": None, "earned_days": 0, "total_days": 0}
    executions = executions or {}
    origin = _baseline_date(creation_date)
    if not origin:
        return {"percent": None, "earned_days": 0, "total_days": None}

    fallback = legacy_dates
    if fallback is None and any(not _field(p, "baseline_due_date") for p in entries):
        fallback = projected_dates(entries, origin)
    fallback = fallback or {}

    days = []
    all_completed = True
    for plan in entries:
        name = _field(plan, "name")
        exe = executions.get(name)
        finished = (
            _field(plan, "plan_state") == "Completed"
            and exe is not None
            and _field(exe, "status") == "Completed"
        )
        all_completed = all_completed and finished
        frozen_date = _field(plan, "baseline_due_date")
        if not frozen_date:
            frozen_date = (fallback.get(name) or {}).get("projected_due_date")
        due = _baseline_date(frozen_date)
        days.append((max(0, (due - origin).days) if due else None, finished))

    if any(day is None for day, _ in days):
        return {
            "percent": 100 if all_completed else None,
            "earned_days": None, "total_days": None,
        }
    total_days = max(day for day, _ in days)
    earned_days = 0
    for day, finished in days:
        if not finished:
            break
        earned_days = max(earned_days, day)
    if all_completed:
        percent = 100
    elif total_days == 0:
        percent = 0
    else:
        # Integer half-up rounding, matching a displayed whole percentage.
        # Never show 100% until EVERY plan is actually complete.
        percent = min(99, (200 * earned_days + total_days) // (2 * total_days))
    return {
        "percent": percent,
        "earned_days": earned_days,
        "total_days": total_days,
    }


def rolling_projected_dates(plans, creation_date, executions=None, step_events=None):
    """Read-only rolling forecast from effective milestone progress.

    Only affected dependency paths move. Already-completed milestone forecasts
    retain the deadline in force at completion (the execution's due_date),
    while their actual completion dates anchor all downstream milestones.

    step_events maps plan ID -> transition rows, newest FIRST. Each event has
    a to_status, action and effective_date / performed_on. It is supplied by
    callers in one batched query; this function has no Frappe database calls.
    """
    executions = executions or {}
    step_events = step_events or {}
    baseline = _baseline_date(creation_date)
    entries = {}
    for plan in plans:
        cfg = json.loads(_field(plan, "workflow_snapshot_json"))
        entries[_field(plan, "milestone_type")] = (plan, cfg, _normal_steps(cfg))
    memo = {}
    visiting = set()

    def actual_step(plan, exe, stage):
        if exe is None or _field(plan, "plan_state") == "Planned":
            return None
        # Rework is intentionally non-deterministic. Do not reuse a past
        # trigger event to forecast a newly returned/rejected dependency.
        if (_field(plan, "plan_state") == "Active" and
                _field(exe, "status") == "Rework"):
            return None
        if stage == "Completed" and _field(plan, "plan_state") == "Completed":
            completed = _baseline_date(_field(exe, "completed_on"))
            if completed:
                return completed
        if _field(exe, "status") == stage:
            return _baseline_date(_field(exe, "step_entered_on"))
        # When a milestone has moved beyond its trigger stage, use the last
        # current-cycle event instead of estimating from planned lead times.
        events = step_events.get(_field(plan, "name"), [])
        for event in events:
            action = _field(event, "action") or ""
            if action in ("Returned to Milestone", "Returned to Future"):
                break
            if (_field(event, "to_status") == stage and
                    action in ("Step " + stage, "Auto Completed",
                               "Auto Activated", "Auto Reactivated")):
                return _baseline_date(_field(event, "effective_date") or
                                      _field(event, "performed_on"))
        return None

    def evaluate(milestone):
        if milestone in memo:
            return memo[milestone]
        if milestone not in entries or milestone in visiting:
            return None
        visiting.add(milestone)
        plan, cfg, steps = entries[milestone]
        exe = executions.get(_field(plan, "name"))
        start = baseline if cfg.get("start_with_design_creation") else None
        parent = cfg.get("depends_on_type") or _field(plan, "depends_on_type")
        if parent and not cfg.get("start_with_design_creation"):
            prior = evaluate(parent)
            trigger = cfg.get("trigger_status") or _field(
                plan, "trigger_status") or "Completed"
            if prior:
                start = prior["step_dates"].get(trigger)
            else:
                start = None

        # Activated milestone's current step and due date are authoritative
        # for its remaining work, even if a predecessor finished early/late.
        state = _field(plan, "plan_state")
        current = _field(exe, "status") if exe is not None else None
        entered = _baseline_date(_field(exe, "step_entered_on")) if exe else None
        normal_names = [x["step"] for x in steps]
        remaining = None
        if current in normal_names and entered and state == "Active":
            index = normal_names.index(current)
            remaining = sum(x["lead_time_days"] for x in steps[index + 1:])
        if state == "Active" and current == "Rework":
            due = None
        elif state == "Active" and remaining is not None:
            due = entered + timedelta(days=remaining)
        elif state == "Completed" and exe and _field(exe, "due_date"):
            # Persisted operational deadline is the pre-completion forecast.
            due = _baseline_date(_field(exe, "due_date"))
        else:
            days = _days_to_step(steps, "Completed")
            due = start + timedelta(days=days) if start and days is not None else None
        step_dates = {}
        for item in steps:
            target = item["step"]
            if target == "Rework":
                continue
            actual = actual_step(plan, exe, target)
            if actual:
                step_dates[target] = actual
            elif start is not None:
                if state == "Active" and current == "Rework":
                    step_dates[target] = None
                elif state == "Active" and current in normal_names and entered:
                    current_idx = normal_names.index(current)
                    target_idx = normal_names.index(target)
                    if target_idx > current_idx:
                        offset = sum(x["lead_time_days"] for x in
                                     steps[current_idx + 1:target_idx + 1])
                        step_dates[target] = entered + timedelta(days=offset)
                    elif target_idx == current_idx:
                        step_dates[target] = entered
                    else:
                        # Past stage without an event cannot be predicted
                        # safely from the current stage.
                        step_dates[target] = None
                else:
                    offset = _days_to_step(steps, target)
                    step_dates[target] = (start + timedelta(days=offset)
                                          if offset is not None else None)
            else:
                step_dates[target] = None
        # For future dependencies Completed is a realized event, not the
        # forecast, even when the predecessor's displayed due stays fixed.
        if state == "Completed" and exe:
            step_dates["Completed"] = actual_step(plan, exe, "Completed")
        result = {
            "start": start, "due": due, "step_dates": step_dates,
            "projected_start_date": start.isoformat() if start else None,
            "projected_due_date": due.isoformat() if due else None,
        }
        visiting.remove(milestone)
        memo[milestone] = result
        return result

    output = {}
    for plan in plans:
        forecast = evaluate(_field(plan, "milestone_type"))
        output[_field(plan, "name")] = {
            "projected_start_date": forecast["projected_start_date"] if forecast else None,
            "projected_due_date": forecast["projected_due_date"] if forecast else None,
        }
    return output
