import frappe
from frappe import _
from frappe.utils import cint,date_diff,flt,getdate,today
def execute(filters=None): f=frappe._dict(filters or {}); return get_columns(),get_data(f)
def get_columns():
    return [{"label":_("Age Days"),"fieldname":"age_days","fieldtype":"Int","width":80},{"label":_("Audit Record"),"fieldname":"audit_record","fieldtype":"Link","options":"Stock Transfer Audit Record","width":150},{"label":_("Audit Run"),"fieldname":"audit_run","fieldtype":"Link","options":"Stock Transfer Audit Run","width":145},{"label":_("Source Warehouse"),"fieldname":"source_warehouse","fieldtype":"Link","options":"Warehouse","width":170},{"label":_("Target Warehouse"),"fieldname":"target_warehouse","fieldtype":"Link","options":"Warehouse","width":170},{"label":_("ABS Variance"),"fieldname":"abs_variance","fieldtype":"Float","precision":3,"width":100},{"label":_("Ignored Qty"),"fieldname":"ignored_qty","fieldtype":"Float","precision":3,"width":95},{"label":_("Correction Required Qty"),"fieldname":"correction_required_qty","fieldtype":"Float","precision":3,"width":135},{"label":_("Draft Corrections"),"fieldname":"draft_corrections","fieldtype":"Int","width":105},{"label":_("Submitted Corrections"),"fieldname":"submitted_corrections","fieldtype":"Int","width":120}]
def get_data(f):
    rf={"docstatus":1,"processing_status":"Pending"}
    if f.source_warehouse: rf["source_warehouse"]=f.source_warehouse
    if f.target_warehouse: rf["target_warehouse"]=f.target_warehouse
    if flt(f.minimum_abs_variance): rf["total_abs_variance_qty"]=[">=",flt(f.minimum_abs_variance)]
    recs=frappe.get_list("Stock Transfer Audit Record",filters=rf,fields=["name","audit_run","source_warehouse","target_warehouse","total_abs_variance_qty","creation"],order_by="creation asc",limit_page_length=0)
    if not recs:return []
    names=[r.name for r in recs]; ignored={}; required={}
    for row in frappe.get_all("Stock Transfer Audit Item",filters={"parent":["in",names],"parenttype":"Stock Transfer Audit Record"},fields=["parent","discrepancy_qty","action"],limit_page_length=0):
        v=flt(row.discrepancy_qty); q=abs(v)
        if row.action=="Ignore": ignored[row.parent]=flt(ignored.get(row.parent))+q
        elif (v>0 and row.action=="Move to Source") or (v<0 and row.action=="Move to Target"): required[row.parent]=flt(required.get(row.parent))+q
    draft={}; submitted={}
    for row in frappe.get_all("Stock Entry",filters={"custom_stock_transfer_audit_record":["in",names]},fields=["custom_stock_transfer_audit_record","docstatus"],limit_page_length=0):
        d=draft if cint(row.docstatus)==0 else submitted if cint(row.docstatus)==1 else None
        if d is not None:d[row.custom_stock_transfer_audit_record]=cint(d.get(row.custom_stock_transfer_audit_record))+1
    now=getdate(today()); min_age=max(cint(f.minimum_age_days),0); out=[]
    for r in recs:
        age=max(date_diff(now,getdate(r.creation)),0)
        if age<min_age:continue
        out.append({"age_days":age,"audit_record":r.name,"audit_run":r.audit_run,"source_warehouse":r.source_warehouse,"target_warehouse":r.target_warehouse,"abs_variance":r.total_abs_variance_qty,"ignored_qty":ignored.get(r.name,0),"correction_required_qty":required.get(r.name,0),"draft_corrections":draft.get(r.name,0),"submitted_corrections":submitted.get(r.name,0)})
    return sorted(out,key=lambda x:(-x["age_days"],-flt(x["abs_variance"])))
