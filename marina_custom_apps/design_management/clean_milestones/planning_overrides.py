"""Per-Design milestone durations frozen into each plan snapshot.

No database calls. The canonical Milestone Master is never modified.
Duration means calendar days from activation to the Completed step.
The first enabled step is entered on activation; conditional Rework is excluded.
"""
from copy import deepcopy
from marina_custom_apps.design_management.clean_milestones.rules import configured_steps

MAX_DESIGN_DURATION_DAYS = 3650


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Milestone lead time must be whole calendar days")
    if isinstance(value, str):
        if not value.strip().isdigit():
            raise ValueError("Milestone lead time must be whole calendar days")
        value = int(value.strip())
    if not 0 <= value <= MAX_DESIGN_DURATION_DAYS:
        raise ValueError("Milestone lead time must be between 0 and 3650 days")
    return value


def normal_steps(config):
    return [stage for stage in configured_steps(config["steps"])
            if stage["step"] != "Rework"]


def milestone_duration(config):
    return sum(stage["lead_time_days"] for stage in normal_steps(config)[1:])


def override_snapshot_duration(config, requested_days):
    """Copy and validate one workflow, scaling its normal step durations."""
    days = _duration(requested_days)
    result = deepcopy(config)
    stages = normal_steps(result)
    old_days = sum(stage["lead_time_days"] for stage in stages[1:])
    if len(stages) == 1:
        if days != 0:
            raise ValueError("Single-step Auto Completed milestones must have zero lead days")
        result["design_lead_time_days"] = 0
        result["master_lead_time_days"] = old_days
        return result
    original = [stage["lead_time_days"] for stage in stages[1:]]
    if old_days:
        cumulative, previous = 0, 0
        allocations = []
        for weight in original:
            cumulative += weight
            rounded = (cumulative * days + old_days // 2) // old_days
            allocations.append(rounded - previous)
            previous = rounded
    else:
        allocations = [0] * (len(stages) - 2) + [days]
    updates = {stage["step"]: value
               for stage, value in zip(stages[1:], allocations)}
    for stage in result["steps"]:
        if stage.get("step") in updates and stage.get("enabled") in (1, "1", True):
            stage["lead_time_days"] = updates[stage["step"]]
    result["master_lead_time_days"] = old_days
    result["design_lead_time_days"] = days
    return result


def apply_duration_overrides(snapshots, overrides):
    """Validate all per-Design overrides before any plan rows are inserted."""
    if not isinstance(overrides, dict):
        raise ValueError("Milestone lead time overrides must be an object")
    allowed = {cfg["name"] for cfg in snapshots}
    if len(overrides) > len(allowed) or set(overrides) - allowed:
        raise ValueError("Lead time override includes an unselected milestone")
    return [override_snapshot_duration(cfg, overrides[cfg["name"]])
            if cfg["name"] in overrides else cfg for cfg in snapshots]
