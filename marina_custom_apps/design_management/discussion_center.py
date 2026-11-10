"""Permission-scoped channel navigation and pinned design context.

Uses existing Mood Board and Design Code records; does not duplicate message data.
"""
import frappe
from marina_custom_apps.design_management.discussions import parent_access


def _term(value, max_length=100):
    if value is None:
        return ""
    if not isinstance(value, str):
        frappe.throw("Invalid discussion filter.")
    value = value.strip()
    if len(value) > max_length:
        frappe.throw("Invalid discussion filter.")
    return value


@frappe.whitelist()
def boards(year=None, season=None, collection=None, design_code=None, offset=0):
    if frappe.session.user == "Guest":
        frappe.throw("Sign in to view discussions.", frappe.PermissionError)
    year, season = _term(year), _term(season)
    collection, design_code = _term(collection), _term(design_code)
    try:
        offset = int(offset)
    except (ValueError, TypeError):
        frappe.throw("Invalid page.")
    if offset < 0 or offset > 100000:
        frappe.throw("Invalid page.")
    filters = {}
    for key, val in (("year", year), ("season", season), ("collection", collection)):
        if val:
            filters[key] = val
    # If filtering by design number, prefilter Mood Boards using a permission-
    # scoped Design Code query; never expose names from unrestricted get_all.
    if design_code:
        ds = frappe.get_list("Design Code", filters={"design_number": ["like", "%" + design_code + "%"]},
            fields=["mood_board"], limit_page_length=1000)
        ids = sorted({d.mood_board for d in ds})
        if not ids:
            return {"rows": [], "has_more": False}
        filters["name"] = ["in", ids]
    rows = frappe.get_list("Mood Board", filters=filters,
        fields=["name", "image", "year", "season", "collection"],
        order_by="name asc", limit_start=offset, limit_page_length=51)
    return {"rows": [dict(x) for x in rows[:50]], "has_more": len(rows) > 50}


@frappe.whitelist()
def designs(mood_board, design_code=None, offset=0):
    parent_access("Mood Board", mood_board)
    design_code = _term(design_code)
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        frappe.throw("Invalid page.")
    if offset < 0 or offset > 100000:
        frappe.throw("Invalid page.")
    filters = {"mood_board": mood_board}
    if design_code:
        filters["design_number"] = ["like", "%" + design_code + "%"]
    # Permission-aware selection FIRST. Do not aggregate messages across
    # inaccessible designs or expose their activity to the client.
    candidates = frappe.get_list("Design Code", filters=filters,
        fields=["name", "design_number", "image"],
        order_by="design_number asc", limit_page_length=5001)
    if len(candidates) > 5000:
        frappe.throw("Too many designs in this Mood Board. Narrow the Design Code filter.")
    if not candidates:
        return {"rows": [], "has_more": False}
    names = [row.name for row in candidates]
    # One grouped query for the whole board; no per-design message/receipt N+1.
    # Latest activity includes system updates but excludes archived/removed
    # messages. Unread excludes the user's own non-system messages.
    stats = frappe.db.sql("""
        SELECT m.reference_name,
               MAX(m.creation) AS last_activity,
               SUM(CASE WHEN (m.owner != %s OR m.is_system = 1)
                    AND COALESCE(r.is_read, 0) = 0 THEN 1 ELSE 0 END) AS unread
        FROM `tabMarina Discussion Message` m
        LEFT JOIN `tabMarina Discussion Receipt` r
          ON r.message = m.name AND r.user = %s
        WHERE m.reference_doctype = 'Design Code'
          AND m.reference_name IN %s AND m.is_archived = 0
          AND m.is_removed = 0
        GROUP BY m.reference_name
    """, (frappe.session.user, frappe.session.user, tuple(names)), as_dict=True)
    by_name = {row.reference_name: row for row in stats}
    # Conversations with activity first, newest activity first. Designs
    # without a conversation remain accessible at the end in code order.
    ordered = sorted(candidates, key=lambda row: (
        0 if row.name in by_name else 1,
        -(by_name[row.name].last_activity.timestamp()) if row.name in by_name else 0,
        row.design_number or row.name))
    batch = ordered[offset:offset + 50]
    rows = []
    for row in batch:
        item = dict(row)
        state = by_name.get(row.name)
        item["unread"] = int(state.unread or 0) if state else 0
        item["last_activity"] = str(state.last_activity) if state else None
        rows.append(item)
    return {"rows": rows, "has_more": offset + len(batch) < len(ordered)}


@frappe.whitelist()
def context(reference_doctype, reference_name):
    doc = parent_access(reference_doctype, reference_name)
    result = {"doctype": reference_doctype, "name": doc.name,
              "image": doc.get("image")}
    if reference_doctype == "Mood Board":
        return result
    from marina_custom_apps.design_management.clean_milestones.schedule import projected_dates, baseline_progress
    plans = frappe.get_all("Design Milestone Plan Entry",
        filters={"design_code": doc.name},
        fields=["name", "milestone_type", "sequence", "plan_state",
                "depends_on_type", "trigger_status", "workflow_snapshot_json", "baseline_due_date", "completion_weight_days"],
        order_by="sequence asc, name asc", limit_page_length=101)
    if len(plans) > 100:
        frappe.throw("Too many milestones for this design.")
    executions = frappe.get_all("Design Milestone Execution",
        filters={"design_code": doc.name}, fields=["name", "plan_entry", "status"],
        limit_page_length=101)
    execution_map = {x.plan_entry: x for x in executions}
    origin = doc.creation_date or doc.creation
    baseline = projected_dates(plans, origin)
    progress = baseline_progress(plans, origin, execution_map, baseline)
    active = [p.milestone_type for p in plans if p.plan_state == "Active"]
    result.update({"mood_board": doc.mood_board, "current_milestones": active,
                   "completion_percent": progress["percent"] if plans else 0})
    return result
