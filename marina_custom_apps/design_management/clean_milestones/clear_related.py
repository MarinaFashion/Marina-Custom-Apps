"""Reset the complete Release 22 milestone workflow for Design Codes.

Reuses the existing Design Code locking and permission model. A reset:
- snapshots all plans, executions, and immutable custody events in a
  write-once Design Cleanup Log with the explicit reason and actor
- removes ONLY those three tables, in child-to-parent order
- leaves Design Code, Creation Date, Design Documents/assignments, items,
  team assignments, files, and production data untouched
- makes Creation Date editable and Create Milestones available again
- is serialized with create_plan, advance and return_to_milestone

Bulk reset is a single Frappe request transaction, not Frappe's independent
List Delete loop. Unexpected errors roll back ALL Design resets. Never commit.
"""
import hashlib
import json

import frappe
from frappe.utils import cint, now_datetime

from marina_custom_apps.design_management.clean_milestones import service
from marina_custom_apps.design_management.security.role_access import can_action

ACTION = "Clear Related Milestones"
MAX_BULK = 20
MAX_RECORDS_PER_TABLE = 2000
MAX_SNAPSHOT_BYTES = 4_000_000
MAX_BULK_SNAPSHOT_BYTES = 12_000_000
TABLES = (
    ("custody_events", "Design Milestone Custody Event"),
    ("executions", "Design Milestone Execution"),
    ("plans", "Design Milestone Plan Entry"),
)


def _names(values):
    if isinstance(values, str):
        values = frappe.parse_json(values)
    if not isinstance(values, list) or not values:
        frappe.throw("Select at least one Design Code")
    if len(values) > MAX_BULK:
        frappe.throw("Select a maximum of 20 Design Codes per milestone reset")
    if any(not isinstance(name, str) or not name.strip() or len(name) > 140
           for name in values):
        frappe.throw("Invalid Design Code selection")
    if len(set(values)) != len(values):
        frappe.throw("Duplicate Design Code selections are not allowed")
    return sorted(values)


def _authorized(design):
    actor = frappe.session.user
    if not can_action(ACTION, actor):
        frappe.throw("Missing Module Action: " + ACTION, frappe.PermissionError)
    if not frappe.has_permission("Design Code", "write", doc=design, user=actor):
        frappe.throw("Write permission required to clear Design milestones",
                     frappe.PermissionError)


def _records(design_code):
    # Fetch all columns for an auditable, recoverable snapshot; bounded to
    # prevent expensive unbounded reads in Frappe Cloud.
    results = {}
    for key, doctype in TABLES:
        rows = frappe.get_all(
            doctype, filters={"design_code": design_code},
            fields=["*"], order_by="name asc",
            limit_page_length=MAX_RECORDS_PER_TABLE + 1,
        )
        if len(rows) > MAX_RECORDS_PER_TABLE:
            frappe.throw("Too many " + doctype +
                         " records for a safe reset. Contact the administrator.")
        results[key] = [dict(row) for row in rows]
    return results


def _payload(design, records):
    return {
        "design_code": design.name,
        "creation_date": str(design.creation_date or "")[:10],
        "workflow": records,
    }


def _encoded(payload):
    raw = json.dumps(payload, default=str, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    byte_count = len(raw.encode("utf-8"))
    if byte_count > MAX_SNAPSHOT_BYTES:
        frappe.throw(
            "Milestone history exceeds the safe audit snapshot size for " +
            payload["design_code"])
    return raw, byte_count


def _state(design):
    records = _records(design.name)
    payload = _payload(design, records)
    packed, byte_count = _encoded(payload)
    return {
        "design_code": design.name,
        "creation_date": payload["creation_date"],
        "plans": len(records["plans"]),
        "completed": sum(row.get("plan_state") == "Completed"
                         for row in records["plans"]),
        "executions": len(records["executions"]),
        "events": len(records["custody_events"]),
        "has_milestones": any(records.values()),
        "revision": hashlib.sha256(packed.encode("utf-8")).hexdigest(),
        "_payload": payload,
        "_bytes": byte_count,
    }


def _public_state(state):
    return {key: val for key, val in state.items()
            if not key.startswith("_")}


def _check_related_references(records):
    """Never silently orphan a standard Frappe ToDo or attached File.

    Published evidence lives on Design Documents and is deliberately NOT
    included: those documents and files survive the reset.
    """
    for _, doctype in TABLES:
        key = next(name for name, dt in TABLES if dt == doctype)
        identifiers = [row["name"] for row in records[key]]
        if not identifiers:
            continue
        for parent_type, parent_field in (
                ("ToDo", "reference_type"), ("File", "attached_to_doctype")):
            name_field = ("reference_name" if parent_type == "ToDo"
                          else "attached_to_name")
            if frappe.db.exists(parent_type, {
                    parent_field: doctype,
                    name_field: ["in", identifiers],
            }):
                frappe.throw(
                    "Milestone records have linked " + parent_type +
                    " entries. Detach these before clearing milestones."
                )


def _inspect(names, lock=False):
    if lock:
        placeholders = ", ".join(["%s"] * len(names))
        locked = frappe.db.sql(
            "SELECT name FROM `tabDesign Code` WHERE name IN (" +
            placeholders + ") ORDER BY name FOR UPDATE",
            tuple(names), as_dict=True)
        if len(locked) != len(names):
            frappe.throw("Some Design Codes changed or no longer exist. Refresh.")
    prepared = []
    total_bytes = 0
    for name in names:
        design = service._design(name)
        _authorized(design)
        state = _state(design)
        total_bytes += state["_bytes"]
        if total_bytes > MAX_BULK_SNAPSHOT_BYTES:
            frappe.throw("Selected milestone history exceeds safe batch size; "
                         "use smaller selections.")
        if state["has_milestones"]:
            _check_related_references(state["_payload"]["workflow"])
        prepared.append(state)
    return prepared


def _preview(names):
    states = _inspect(names)
    return {
        "selected": len(states),
        "with_milestones": sum(bool(s["has_milestones"]) for s in states),
        "without_milestones": sum(not s["has_milestones"] for s in states),
        "designs": [_public_state(s) for s in states],
    }


@frappe.whitelist()
def can_clear_milestones_action():
    """Visibility hint for List View; per-Design checks remain authoritative."""
    return bool(can_action(ACTION) and
                frappe.has_permission("Design Code", "write"))


@frappe.whitelist()
def can_clear_related_milestones(design_code):
    # Evaluate action and native record-level scope independently.
    design = service._design(design_code)
    return bool(
        can_action(ACTION) and
        frappe.has_permission("Design Code", "write", doc=design)
    )


@frappe.whitelist()
def preview_clear_related_milestones(design_code):
    return _preview(_names([design_code]))


@frappe.whitelist()
def preview_bulk_clear_related_milestones(design_codes):
    return _preview(_names(design_codes))


def _clear(prepared, reason):
    design_code = prepared["design_code"]
    records = prepared["_payload"]["workflow"]
    snapshot = {
        **prepared["_payload"],
        "operation": ACTION,
        "performed_by": frappe.session.user,
        "reason": reason,
    }
    packed, _ = _encoded(snapshot)
    frappe.get_doc({
        "doctype": "Design Cleanup Log",
        "design_code_ref": design_code,
        "operation": ACTION,
        "performed_by": frappe.session.user,
        "performed_on": now_datetime(),
        "reason": reason,
        "snapshot": packed,
    }).insert(ignore_permissions=True)

    # Use direct, scoped deletes because milestone DocTypes deliberately
    # forbid ordinary on_trash, and all links are internal to this workflow.
    for _, doctype in TABLES:
        frappe.db.delete(doctype, {"design_code": design_code})

    return {
        "design_code": design_code,
        "plans": prepared["plans"],
        "executions": prepared["executions"],
        "events": prepared["events"],
        "audit_logged": True,
    }


def _execute(names, reason, revisions, confirm):
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 500:
        frappe.throw("Enter a reason for clearing milestones (10-500 characters)")
    if not cint(confirm):
        frappe.throw("Confirm clearing all milestone history")
    if isinstance(revisions, str):
        revisions = frappe.parse_json(revisions)
    if not isinstance(revisions, dict) or set(revisions) != set(names):
        frappe.throw("Preview the selected Design Codes before confirming")
    if any(not isinstance(revisions[name], str) or len(revisions[name]) != 64
           for name in names):
        frappe.throw("Invalid milestone preview; refresh and try again")

    prepared = _inspect(names, lock=True)
    for state in prepared:
        if state["revision"] != revisions[state["design_code"]]:
            frappe.throw(
                "Milestones changed since preview for " + state["design_code"] +
                ". Review the current milestone data before clearing."
            )

    cleared = []
    skipped = []
    for state in prepared:
        if not state["has_milestones"]:
            skipped.append(state["design_code"])
            continue
        cleared.append(_clear(state, reason))

    return {
        "selected": len(prepared),
        "cleared": len(cleared),
        "skipped": len(skipped),
        "cleared_designs": cleared,
        "skipped_designs": skipped,
        "documents_preserved": True,
        "production_preserved": True,
    }


@frappe.whitelist(methods=["POST"])
def clear_related_milestones(design_code, reason, expected_revision, confirm=0):
    return _execute(
        _names([design_code]), reason,
        {design_code: expected_revision}, confirm,
    )


@frappe.whitelist(methods=["POST"])
def bulk_clear_related_milestones(design_codes, reason, expected_revisions,
                                  confirm=0):
    return _execute(_names(design_codes), reason, expected_revisions, confirm)
