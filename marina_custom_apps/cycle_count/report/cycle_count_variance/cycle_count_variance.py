import frappe
from frappe import _
def execute(filters=None):
    filters=filters or {}; cond=["p.docstatus in (0,1)","i.counted=1","abs(i.variance_qty)>0.000001"];v={}
    if filters.get("company"):cond.append("p.company=%(company)s");v["company"]=filters["company"]
    if filters.get("warehouse"):cond.append("p.warehouse=%(warehouse)s");v["warehouse"]=filters["warehouse"]
    cols=[{"label":_("Store Cycle Count"),"fieldname":"store_cycle_count","fieldtype":"Link","options":"Store Cycle Count","width":160},{"label":_("Store"),"fieldname":"warehouse","fieldtype":"Link","options":"Warehouse","width":180},{"label":_("Item"),"fieldname":"item_code","fieldtype":"Link","options":"Item","width":140},{"label":_("Style"),"fieldname":"item_template","fieldtype":"Link","options":"Item","width":140},{"label":_("System Qty"),"fieldname":"system_qty","fieldtype":"Float","width":95},{"label":_("Physical Qty"),"fieldname":"counted_qty","fieldtype":"Float","width":95},{"label":_("Variance Qty"),"fieldname":"variance_qty","fieldtype":"Float","width":95},{"label":_("Variance Value"),"fieldname":"variance_value","fieldtype":"Currency","width":120}]
    q=f"""select p.name store_cycle_count,p.warehouse,i.item_code,i.item_template,i.system_qty,i.counted_qty,i.variance_qty,i.variance_value from `tabStore Cycle Count Item` i join `tabStore Cycle Count` p on p.name=i.parent where {' and '.join(cond)} order by p.count_date desc,p.warehouse,i.item_template,i.item_code"""
    return cols,frappe.db.sql(q,v,as_dict=True)
