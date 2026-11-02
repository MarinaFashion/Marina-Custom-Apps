"""Controlled bulk initialization of Design milestone plans.

Reuses the authoritative service.create_plan for every eligible Design Code:
* Each Design's persisted Creation Date is its own planning baseline.
* All currently active Milestone Types are included in master sequence order.
* Existing Designer, image, custody, RBAC, evidence and snapshot rules apply.
* The bulk method does not use ignore_permissions, db_set or direct plan inserts.

Maximum 20 designs per operation to bound runtime and Frappe Cloud workload.
Already initialized/ineligible designs are skipped with transparent reasons.
All *eligible* designs are created atomically within one Frappe request: a
late validation error rolls back the whole request, never a partial plan.
"""
from datetime import date

import frappe
from frappe.utils import cint, getdate, today

from marina_custom_apps.design_management.clean_milestones import service
from marina_custom_apps.design_management.clean_milestones.rules import configured_steps
from marina_custom_apps.design_management.clean_milestones.evidence import (
    matching_published_documents,
)
from marina_custom_apps.design_management.security.organization import role_catalog, user_roles
from marina_custom_apps.design_management.security.participants import is_participant

MAX_BULK_DESIGNS = 20


def _names(selected):
    if isinstance(selected, str):
        selected = frappe.parse_json(selected)
    if not isinstance(selected, list) or not selected:
        frappe.throw("Select at least one Design Code")
    if len(selected) > MAX_BULK_DESIGNS:
        frappe.throw("Select a maximum of 20 Design Codes for bulk milestone creation")
    if any(not isinstance(value, str) or not value or len(value) > 140
           for value in selected):
        frappe.throw("Invalid Design Code selection")
    if len(set(selected)) != len(selected):
        frappe.throw("Duplicate Design Code selections are not allowed")
    return sorted(selected)


def _active_milestones():
    rows = frappe.get_all(
        "Design Milestone Type",
        filters={"is_active": 1},
        fields=["name", "sequence"],
        order_by="sequence asc, name asc",
        limit_page_length=service.MAX_SELECTED + 1,
    )
    if not rows or len(rows) > service.MAX_SELECTED:
        frappe.throw("Configure between 1 and 50 active Milestone Types")
    types = [row.name for row in rows]
    # Validate the full dependency graph and each workflow master once.
    snapshots = service._snapshots(types)
    return types, snapshots


def _ready_state(design, snapshots, roles):
    """Preview prerequisites without writing or changing the Design."""
    name = design.name
    if frappe.db.exists("Design Milestone Plan Entry", {"design_code": name}):
        return "existing", ["A milestone plan already exists"]

    issues = []
    baseline = design.creation_date
    if not baseline:
        issues.append("Creation Date is missing")
    elif getdate(baseline) > getdate(today()):
        issues.append("Creation Date cannot be in the future")
    if not design.image:
        issues.append("Main Image is missing")

    assigned = {}
    for row in (design.get("r22_team_assignments") or []):
        if row.active and row.module_role:
            assigned.setdefault(row.module_role, []).append(row.user)

    required = {"Designer"}
    for snapshot in snapshots:
        for step in configured_steps(snapshot["steps"]):
            for key in ("custody_role", "responsible_module_role"):
                if step[key]:
                    required.add(step[key])
    for role in sorted(required):
        users = assigned.get(role, [])
        if len(users) != 1 or not users[0]:
            issues.append("Assign exactly one active " + role)
        elif (role not in roles or role not in user_roles(users[0])
              or not is_participant(users[0])):
            issues.append("Invalid or ineligible " + role + " assignment")

    for snapshot in snapshots:
        steps = configured_steps(snapshot["steps"])
        if (len(steps) == 1 and steps[0]["step"] == "Completed"
                and steps[0]["transition_mode"] == "Auto"):
            # Same Published evidence requirement enforced by service._activate.
            docs = matching_published_documents(name, snapshot["name"])
            if len(docs) != 1:
                issues.append(
                    "Exactly one linked Published evidence document required for "
                    + snapshot["name"]
                )

    return ("blocked", issues) if issues else ("ready", [])


def _inspect(names, snapshots):
    roles = role_catalog()
    result = []
    for name in names:
        design = service._design(name)
        design.check_permission("write")
        service._authorize(frappe.session.user, "Assign Milestones", design)
        status, issues = _ready_state(design, snapshots, roles)
        result.append({
            "design_code": name,
            "creation_date": str(design.creation_date or "")[:10],
            "status": status,
            "reasons": issues,
        })
    return result


def _summary(rows, types):
    return {
        "selected": len(rows),
        "ready": sum(row["status"] == "ready" for row in rows),
        "existing": sum(row["status"] == "existing" for row in rows),
        "blocked": sum(row["status"] == "blocked" for row in rows),
        "milestones_per_design": len(types),
        "milestone_types": types,
        "designs": rows,
    }


@frappe.whitelist(methods=["POST"])
def preview_bulk_create_milestones(design_codes):
    names = _names(design_codes)
    types, snapshots = _active_milestones()
    return _summary(_inspect(names, snapshots), types)


@frappe.whitelist(methods=["POST"])
def bulk_create_milestones(design_codes, confirm=0):
    if not cint(confirm):
        frappe.throw("Confirm bulk milestone creation")
    names = _names(design_codes)
    types, snapshots = _active_milestones()

    # Lock in deterministic order, like Designer bulk assignment. The
    # service repeats its own row-lock/date/permission checks on every Design.
    placeholders = ", ".join(["%s"] * len(names))
    locked = frappe.db.sql(
        "SELECT name FROM `tabDesign Code` WHERE name IN (" + placeholders +
        ") ORDER BY name FOR UPDATE",
        tuple(names),
        as_dict=True,
    )
    if len(locked) != len(names):
        frappe.throw("Selected Design Codes changed or no longer exist; refresh the list")

    rows = _inspect(names, snapshots)
    created = []
    for row in rows:
        if row["status"] != "ready":
            continue
        # Never bypass single-Design validation or change its lead times.
        # A late error aborts this request and rolls back all newly-created
        # plans (Frappe owns the transaction; NO per-record commits).
        outcome = service.create_plan(row["design_code"], types)
        created.append({
            "design_code": row["design_code"],
            "creation_date": row["creation_date"],
            "planned": outcome["planned"],
            "activated": outcome["activated"],
        })

    return {
        **_summary(rows, types),
        "created": len(created),
        "created_designs": created,
    }
