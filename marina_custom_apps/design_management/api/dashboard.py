"""Permission-scoped summary based only on active Design executions."""
import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def get_design_dashboard(year=None, season=None, mood_board=None,
                         assigned_merchandiser=None, development_stage=None,
                         deadline_status=None):
    if not frappe.has_permission("Design Code", "read"):
        frappe.throw("Not authorized for Design Dashboard", frappe.PermissionError)
    design_scope=frappe.get_list("Design Code",fields=["name"],order_by="",
                                 limit_page_length=0,run=False)
    if not isinstance(design_scope,str):
        frappe.throw("Could not compile authorized Design scope")
    clauses=["d.name IN ("+design_scope+")"]
    params={"today":today(),"soon":add_days(today(),7)}
    for field,value in (("year",year),("season",season),("mood_board",mood_board),
                        ("assigned_merchandiser",assigned_merchandiser),
                        ("development_stage",development_stage)):
        if value:
            clauses.append("d.`"+field+"` = %("+field+")s")
            params[field]=value
    overdue=("EXISTS (SELECT 1 FROM `tabDesign Milestone Execution` x "
             "WHERE x.design_code=d.name AND x.status!='Completed' "
             "AND x.due_date < %(today)s)")
    if deadline_status=="Delayed":
        clauses.append(overdue)
    elif deadline_status=="On Track":
        clauses.append("NOT "+overdue)
    elif deadline_status not in ("",None):
        frappe.throw("Invalid deadline filter")
    where=" AND ".join(clauses)
    totals=frappe.db.sql("""
        SELECT COUNT(*) total,
            SUM(d.development_stage='In Production') in_production,
            SUM(d.condition IN ('Blocked','On Hold')) blocked_hold
        FROM `tabDesign Code` d WHERE """+where,params,as_dict=True)[0]
    stages=frappe.db.sql("""
        SELECT COALESCE(d.development_stage,'Unspecified') stage,COUNT(*) designs
        FROM `tabDesign Code` d WHERE """+where+"""
        GROUP BY d.development_stage ORDER BY designs DESC
    """,params,as_dict=True)
    milestone=frappe.db.sql("""
        SELECT
          COUNT(DISTINCT IF(x.status!='Completed'
             AND x.due_date < %(today)s,d.name,NULL)) overdue_designs,
          COUNT(DISTINCT IF(x.status!='Completed'
             AND x.due_date BETWEEN %(today)s AND %(soon)s,d.name,NULL)) upcoming
        FROM `tabDesign Code` d
        LEFT JOIN `tabDesign Milestone Execution` x ON x.design_code=d.name
        WHERE """+where,params,as_dict=True)[0]
    return {"total":totals.total or 0,"in_production":totals.in_production or 0,
            "blocked_hold":totals.blocked_hold or 0,
            "delayed":milestone.overdue_designs or 0,
            "upcoming":milestone.upcoming or 0,"stages":stages}
