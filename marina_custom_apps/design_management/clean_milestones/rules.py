"""Small, deterministic step and trigger rules for the new milestone module.

There is no Strict/Skip/Direct workflow flag or mandatory Ready/Review stage,
and no global sequential frontier. Explicit milestone+step events activate
successors, even while another milestone is still in progress.
"""
from collections.abc import Mapping

STEPS = ("Ready to Start", "In Progress", "Ready", "Rework", "Completed")
STEP_INDEX = {"Ready to Start": 0, "In Progress": 1, "Ready": 2, "Completed": 3}
TRANSITIONS = ("Auto", "Manual")


class ConfigurationError(ValueError):
    pass


def attr(row, name, default=None):
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def checked(value):
    return value in (1, True, "1")


def configured_steps(rows):
    result = []
    seen = set()
    for row in list(rows or []):
        if not checked(attr(row, "enabled")):
            continue
        step = str(attr(row, "step") or "").strip()
        mode = str(attr(row, "transition_mode") or "Manual").strip()
        actor = str(attr(row, "responsible_module_role") or "").strip() or None
        owner = str(attr(row, "custody_role") or "").strip() or None
        evidence = str(attr(row, "evidence_type") or "").strip() or None
        required = checked(attr(row, "requires_evidence"))
        try:
            lead = int(attr(row, "lead_time_days") or 0)
        except (ValueError, TypeError) as exc:
            raise ConfigurationError("Lead Time To Complete must be a whole number") from exc
        if step not in STEPS or step in seen or mode not in TRANSITIONS:
            raise ConfigurationError("Invalid or duplicate enabled milestone step")
        if not owner:
            raise ConfigurationError("Select Custody Role for " + step)
        if mode == "Manual" and not actor:
            raise ConfigurationError("Select Who Can Select for manual step " + step)
        if required and not evidence:
            raise ConfigurationError("Select Evidence Type for " + step)
        if lead < 0 or lead > 3650:
            raise ConfigurationError("Lead Time must be between 0 and 3650 days")
        seen.add(step)
        result.append({
            "step": step, "enabled": True, "transition_mode": mode,
            "responsible_module_role": actor, "custody_role": owner,
            "lead_time_days": lead, "requires_evidence": required,
            "evidence_type": evidence if required else None,
        })
    if not result or "Completed" not in seen:
        raise ConfigurationError("Each milestone requires an enabled Completed step")
    if result[0]["transition_mode"] != "Auto":
        raise ConfigurationError("The first milestone step must be Auto")
    if any(r["step"] == "Rework" and r["transition_mode"] != "Manual" for r in result):
        raise ConfigurationError("Rework must be manually selected by an authorized reviewer")
    # Rework is a conditional choice, not sequential execution.
    normal = [r["step"] for r in result if r["step"] != "Rework"]
    if normal != sorted(normal, key=lambda x: STEP_INDEX[x]):
        raise ConfigurationError("Normal steps must progress toward Completed in order")
    return result


def validate_master_definition(config):
    begin = checked(attr(config, "start_with_design_creation"))
    prior = attr(config, "depends_on_type")
    trigger = attr(config, "trigger_status") or "Completed"
    if begin and prior:
        raise ConfigurationError("Design Creation milestone cannot have a previous milestone")
    if not begin and not prior:
        raise ConfigurationError("Select Start After Milestone or Start with Design Creation")
    if trigger not in STEPS:
        raise ConfigurationError("Trigger step is not a supported workflow step")
    steps = configured_steps(attr(config, "steps") or [])
    roles = {r[k] for r in steps
             for k in ("responsible_module_role", "custody_role") if r[k]}
    types = {r["evidence_type"] for r in steps if r["requires_evidence"]}
    return roles, types


def trigger_matches(trigger_milestone, trigger_step, event_milestone, event_step):
    return bool(trigger_milestone and trigger_step and
                trigger_milestone == event_milestone and trigger_step == event_step)


def initial_step(rows):
    return configured_steps(rows)[0]


def allowed_next(steps, current, proposed):
    """Manual actions follow configured normal steps; Rework is a review branch.

    When Ready is configured the worker must submit it before a reviewer can
    reject or complete. After Rework, the worker must resubmit Ready; direct
    Rework -> Completed is forbidden. Milestones without Ready keep their
    simpler legacy-free Rework/Completed behavior.
    """
    active = configured_steps(steps)
    names = [r["step"] for r in active]
    if current == "Completed" or proposed not in names or proposed == current:
        return False
    if proposed == "Rework":
        if "Rework" not in names:
            return False
        return current == "Ready" if "Ready" in names else (
            current in ("In Progress", "Ready to Start"))
    if current == "Rework":
        if "Ready" in names:
            # Correction returns custody to the reviewer only when the
            # responsible employee explicitly reports Ready again.
            return proposed == "Ready"
        # Simpler masters have no Ready review handoff. Their authorized
        # reviewer may confirm correction and completion directly.
        return proposed == "Completed" or (
            proposed == "In Progress" and "In Progress" in names)
    normal = [x for x in names if x != "Rework"]
    return current in normal and normal.index(proposed) == normal.index(current) + 1
