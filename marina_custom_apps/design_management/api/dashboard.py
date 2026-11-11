"""Read-only, permission-scoped Release 22 Design Management Dashboard.

Each milestone is counted once per Design Code. Active categories may
overlap because Release 22 allows parallel milestones. Historical plans
without stored weights use their immutable workflow snapshots.
"""
import json

import frappe
from frappe.utils import add_days, today

from marina_custom_apps.design_management.clean_milestones.schedule import (
    milestone_weight_days,
)

MAX_PROGRESS_ROWS = 20000


def _scope(year=None, season=None, collection=None, drop=None, mood_board=None,
           assigned_merchandiser=None, current_milestone=None,
           deadline_status=None):
    if not frappe.has_permission("Design Code", "read"):
        frappe.throw("Not authorized for Design Dashboard", frappe.PermissionError)
    scope = frappe.get_list(
        "Design Code", fields=["name"], order_by="",
        limit_page_length=0, run=False,
    )
    if not isinstance(scope, str):
        frappe.throw("Could not compile authorized Design scope")

    conditions = ["d.name IN (" + scope + ")"]
    params = {"today": today(), "soon": add_days(today(), 7)}

    # Whitelisted field identifiers; never interpolate user-provided SQL.
    for field, value in (
        ("year", year), ("season", season), ("collection", collection),
        ("drop", drop), ("mood_board", mood_board),
        ("assigned_merchandiser", assigned_merchandiser),
    ):
        if value:
            if not isinstance(value, str) or len(value) > 140:
                frappe.throw("Invalid " + field + " filter")
            conditions.append("d.`" + field + "` = %(" + field + ")s")
            params[field] = value

    if current_milestone:
        if not isinstance(current_milestone, str) or len(current_milestone) > 140:
            frappe.throw("Invalid Current Milestone filter")
        conditions.append(
            "EXISTS (SELECT 1 FROM `tabDesign Milestone Plan Entry` f "
            "WHERE f.design_code=d.name AND f.plan_state='Active' "
            "AND f.milestone_type=%(current_milestone)s)"
        )
        params["current_milestone"] = current_milestone

    overdue = (
        "EXISTS (SELECT 1 FROM `tabDesign Milestone Plan Entry` q "
        "INNER JOIN `tabDesign Milestone Execution` x "
        "ON x.name=q.activated_execution AND x.design_code=q.design_code "
        "WHERE q.design_code=d.name AND q.plan_state='Active' "
        "AND x.status!='Completed' AND x.due_date < %(today)s)"
    )
    if deadline_status == "Delayed":
        conditions.append(overdue)
    elif deadline_status == "On Track":
        conditions.append("NOT " + overdue)
    elif deadline_status not in (None, ""):
        frappe.throw("Invalid Deadline Status filter")
    return " AND ".join(conditions), params


def _progress(where, params):
    """Average each Design Code's weighted completion, including legacy plans.

    Fetch plans in one bounded permission-scoped query, then calculate using
    the same saved-weight/legacy-fallback rules as the Follow-Up Grid.
    Unplanned Designs count as 0%, rather than disappearing from the average.
    """
    plans = frappe.db.sql("""
        SELECT p.design_code, p.name, p.plan_state, p.completion_weight_days,
               p.workflow_snapshot_json, x.status AS execution_status
        FROM `tabDesign Code` d
        INNER JOIN `tabDesign Milestone Plan Entry` p ON p.design_code=d.name
        LEFT JOIN `tabDesign Milestone Execution` x
          ON x.name=p.activated_execution AND x.design_code=p.design_code
        WHERE """ + where + """
        ORDER BY p.design_code, p.sequence, p.name
        LIMIT %(progress_limit)s
    """, {**params, "progress_limit": MAX_PROGRESS_ROWS + 1}, as_dict=True)
    if len(plans) > MAX_PROGRESS_ROWS:
        frappe.throw("Too many milestone plans for dashboard summary. Narrow the filters.")

    totals = {}
    for plan in plans:
        weight = plan.completion_weight_days
        if not weight or int(weight) <= 0:
            weight = milestone_weight_days(json.loads(plan.workflow_snapshot_json))
        weight = int(weight)
        values = totals.setdefault(plan.design_code, [0, 0])
        values[1] += weight
        if plan.plan_state == "Completed" and plan.execution_status == "Completed":
            values[0] += weight
    # Weighted *per design*, not weighted by number of milestones/duration.
    return sum(
        min(100, (100 * earned / total)) for earned, total in totals.values() if total
    )


@frappe.whitelist()
def get_design_dashboard(year=None, season=None, mood_board=None,
                         assigned_merchandiser=None, development_stage=None,
                         deadline_status=None, collection=None, drop=None,
                         current_milestone=None):
    # Accept the deprecated keyword only as empty; never silently apply its
    # obsolete Design Code field to modern milestone reporting.
    if development_stage:
        frappe.throw("Development Stage is obsolete; use Current Milestone")
    where, params = _scope(
        year, season, collection, drop, mood_board, assigned_merchandiser,
        current_milestone, deadline_status,
    )
    summary = frappe.db.sql("""
        SELECT COUNT(*) AS total,
          SUM(d.condition IN ('Blocked','On Hold')) AS blocked_hold,
          SUM(EXISTS (
            SELECT 1 FROM `tabDesign Milestone Plan Entry` p
            WHERE p.design_code=d.name AND p.milestone_type='Bulk Production'
              AND p.plan_state IN ('Active','Completed')
          )) AS in_bulk_production,
          SUM(EXISTS (
            SELECT 1 FROM `tabDesign Milestone Plan Entry` p
            INNER JOIN `tabDesign Milestone Execution` x
              ON x.name=p.activated_execution AND x.design_code=p.design_code
            WHERE p.design_code=d.name AND p.plan_state='Active'
              AND x.status!='Completed' AND x.due_date < %(today)s
          )) AS delayed,
          SUM(EXISTS (
            SELECT 1 FROM `tabDesign Milestone Plan Entry` p
            INNER JOIN `tabDesign Milestone Execution` x
              ON x.name=p.activated_execution AND x.design_code=p.design_code
            WHERE p.design_code=d.name AND p.plan_state='Active'
              AND x.status!='Completed'
              AND x.due_date BETWEEN %(today)s AND %(soon)s
          )) AS upcoming
        FROM `tabDesign Code` d WHERE """ + where, params, as_dict=True)[0]

    distribution = frappe.db.sql("""
        SELECT p.milestone_type, COUNT(DISTINCT d.name) AS designs
        FROM `tabDesign Code` d
        INNER JOIN `tabDesign Milestone Plan Entry` p ON p.design_code=d.name
        INNER JOIN `tabDesign Milestone Execution` x
          ON x.name=p.activated_execution AND x.design_code=p.design_code
        WHERE """ + where + """
          AND p.plan_state='Active' AND x.status!='Completed'
        GROUP BY p.milestone_type
        ORDER BY designs DESC, p.milestone_type ASC
    """, params, as_dict=True)

    completed = frappe.db.sql("""
        SELECT p.milestone_type, COUNT(DISTINCT d.name) AS designs
        FROM `tabDesign Code` d
        INNER JOIN `tabDesign Milestone Plan Entry` p ON p.design_code=d.name
        INNER JOIN `tabDesign Milestone Execution` x
          ON x.name=p.activated_execution AND x.design_code=p.design_code
        WHERE """ + where + """
          AND p.plan_state='Completed' AND x.status='Completed'
        GROUP BY p.milestone_type
        ORDER BY designs DESC, p.milestone_type ASC
    """, params, as_dict=True)

    count = int(summary.total or 0)
    # Zero-plan Designs are included in denominator with 0 completion.
    progress_sum = _progress(where, params) if count else 0
    return {
        "total": count,
        "in_bulk_production": int(summary.in_bulk_production or 0),
        "blocked_hold": int(summary.blocked_hold or 0),
        "delayed": int(summary.delayed or 0),
        "upcoming": int(summary.upcoming or 0),
        "average_completion": round(progress_sum / count, 1) if count else 0,
        "current_milestones": distribution,
        "completed_milestones": completed,
    }

@frappe.whitelist()
def get_dashboard_mood_board_options(year=None, season=None, collection=None,
                                    drop=None):
    """Accessible Mood Boards used by designs in the selected hierarchy.

    Scopes options to readable Design Codes; no access through get_all and no
    unrestricted Mood Board enumeration.
    """
    where, params = _scope(
        year=year, season=season, collection=collection, drop=drop
    )
    rows = frappe.db.sql("""
        SELECT DISTINCT d.mood_board
        FROM `tabDesign Code` d
        WHERE """ + where + """
          AND d.mood_board IS NOT NULL AND d.mood_board != ''
        ORDER BY d.mood_board
        LIMIT 501
    """, params, as_dict=True)
    if len(rows) > 500:
        frappe.throw("Too many Mood Boards for dashboard dropdown; narrow filters")
    return [row.mood_board for row in rows]
