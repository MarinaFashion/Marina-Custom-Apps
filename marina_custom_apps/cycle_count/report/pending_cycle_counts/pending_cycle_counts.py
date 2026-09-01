import frappe
from frappe import _
def execute(filters=None):
    filters=filters or {}; cols=[{"label":_("Store Cycle Count"),"fieldname":"name","fieldtype":"Link","options":"Store Cycle Count","width":160},{"label":_("Store"),"fieldname":"warehouse","fieldtype":"Link","options":"Warehouse","width":190},{"label":_("Assigned User"),"fieldname":"assigned_to","fieldtype":"Link","options":"User","width":180},{"label":_("Status"),"fieldname":"status","fieldtype":"Data","width":140},{"label":_("Count Date"),"fieldname":"count_date","fieldtype":"Date","width":110}]
    f={"docstatus":0,"status":["not in",["Reconciled","Cancelled"]]};
    if filters.get("company"):f["company"]=filters["company"]
    return cols,frappe.get_all("Store Cycle Count",filters=f,fields=[c["fieldname"] for c in cols],order_by="count_date asc, warehouse asc",limit_page_length=0)
