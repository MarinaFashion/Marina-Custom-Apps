"""Bulk Designer assignment from the standard Design Code List.

The Team Assignments child table is the only responsibility authority.
Design Code.designer is a read-only projection and is updated by the existing
DesignCode.before_validate hook; never write it directly.

All selected records are updated in one request/transaction. Frappe rolls back
the entire batch if any Design validation, permission or custody update fails.
"""
import frappe
from frappe.utils import cint

from marina_custom_apps.design_management.security.organization import (
    can_manage_role, role_catalog, user_roles,
)
from marina_custom_apps.design_management.security.role_access import can_action
from marina_custom_apps.design_management.security.participants import is_participant

MAX_BULK_DESIGNS = 50
DESIGNER_ROLE = "Designer"
BULK_REASON = "Assigned Designer through Design Code List"


def _admin(actor):
    return actor == "Administrator" or "System Manager" in frappe.get_roles(actor)


def _design_names(values):
    if isinstance(values, str):
        values = frappe.parse_json(values)
    if not isinstance(values, list) or not values:
        frappe.throw("Select at least one Design Code")
    if len(values) > MAX_BULK_DESIGNS:
        frappe.throw("Select a maximum of 50 Design Codes per operation")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 140
           for v in values):
        frappe.throw("Invalid Design Code selection")
    if len(set(values)) != len(values):
        frappe.throw("Duplicate Design Codes are not allowed")
    return sorted(values)


def _authorize(actor):
    if not _admin(actor) and (
            not can_action("Reassign Team Tasks", actor)
            or not can_manage_role(actor, DESIGNER_ROLE)):
        frappe.throw("Not authorized to assign the Designer role",
                     frappe.PermissionError)
    if DESIGNER_ROLE not in role_catalog():
        frappe.throw("The Designer module role is not enabled")


def _eligible_designer(user):
    if (not isinstance(user, str) or not user or
            not is_participant(user) or DESIGNER_ROLE not in user_roles(user)):
        frappe.throw(
            "Choose an active Marina Design Participant with the Designer module role"
        )


def _designer_row(design):
    active = [row for row in (design.get("r22_team_assignments") or [])
              if row.module_role == DESIGNER_ROLE and row.active]
    if len(active) > 1:
        frappe.throw("Design " + design.name +
                     " has multiple active Designer rows; resolve this first")
    return active[0] if active else None


def _read_selection(names):
    # Every row is checked with native Frappe permissions, including
    # assignment scope; selecting records in the List is not permission.
    designs = []
    for name in names:
        design = frappe.get_doc("Design Code", name)
        design.check_permission("write")
        designs.append(design)
    return designs


@frappe.whitelist(methods=["POST"])
def preview_bulk_designer_assignment(design_codes):
    names = _design_names(design_codes)
    _authorize(frappe.session.user)
    designs = _read_selection(names)
    assigned = []
    unassigned = []
    for doc in designs:
        row = _designer_row(doc)
        if row and row.user:
            assigned.append(doc.name)
        else:
            unassigned.append(doc.name)
    return {
        "total": len(designs),
        "assigned": len(assigned),
        "unassigned": len(unassigned),
        "assigned_designs": assigned,
        "unassigned_designs": unassigned,
    }


@frappe.whitelist(methods=["POST"])
def bulk_assign_designer(design_codes, designer, replace_existing=0,
                         reason=None, confirm_replace=0):
    names = _design_names(design_codes)
    actor = frappe.session.user
    _authorize(actor)
    _eligible_designer(designer)

    replacing = bool(cint(replace_existing))
    confirmed = bool(cint(confirm_replace))
    reason = (reason or "").strip()
    if replacing and (not confirmed or len(reason) < 10 or len(reason) > 500):
        frappe.throw(
            "Replacing existing Designers requires confirmation and a reason (10-500 characters)"
        )

    # Serialize concurrent assignment and milestone creation on Design Code
    # rows, sorted to reduce deadlock risk. No partial commits or savepoints.
    placeholders = ", ".join(["%s"] * len(names))
    locked = frappe.db.sql(
        "SELECT name FROM `tabDesign Code` WHERE name IN (" + placeholders +
        ") ORDER BY name FOR UPDATE", tuple(names), as_dict=True,
    )
    if len(locked) != len(names):
        frappe.throw("Some selected Design Codes no longer exist; refresh the list")

    designs = _read_selection(names)
    # Prepare all changes against the locked, current records before saving
    # any; no duplicate rows and no replacement of equal assignments.
    changes = []
    skipped = []
    for doc in designs:
        row = _designer_row(doc)
        current = row.user if row and row.user else None
        if current == designer:
            skipped.append(doc.name)
            continue
        if current and not replacing:
            skipped.append(doc.name)
            continue
        changes.append((doc, row, current))

    for doc, row, old in changes:
        note = reason if old else BULK_REASON
        if row:
            row.user = designer
            row.active = 1
            row.assignment_note = note
        else:
            # Reactivate an existing inactive row instead of duplicating it.
            inactive = next((
                item for item in (doc.get("r22_team_assignments") or [])
                if item.module_role == DESIGNER_ROLE and not item.active
            ), None)
            if inactive:
                inactive.user = designer
                inactive.active = 1
                inactive.assignment_note = note
            else:
                doc.append("r22_team_assignments", {
                    "module_role": DESIGNER_ROLE,
                    "user": designer,
                    "active": 1,
                    "default_for_design": 0,
                    "assignment_note": note,
                })
        # Normal DesignCode save enforces participant/module-role validity,
        # manager permissions and reassignment reason, and transfers active
        # custody with an append-only milestone event. It also projects
        # the designer field automatically.
        doc.save()

    return {
        "selected": len(names),
        "updated": len(changes),
        "skipped": len(skipped),
        "updated_designs": [doc.name for doc, _, _ in changes],
        "skipped_designs": skipped,
    }
