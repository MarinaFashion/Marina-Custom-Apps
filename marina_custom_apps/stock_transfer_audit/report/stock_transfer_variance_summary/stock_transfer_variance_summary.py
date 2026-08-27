import frappe
from frappe import _
from frappe.utils import flt,getdate
def execute(filters=None):
    f=frappe._dict(filters or {})
    if not f.from_date or not f.to_date: frappe.throw(_("From Date and To Date are required."))
    if getdate(f.from_date)>getdate(f.to_date): frappe.throw(_("From Date cannot be after To Date."))
    return get_columns(),get_data(f)
def get_columns():
    return [{"label":_("Target Warehouse"),"fieldname":"target_warehouse","fieldtype":"Link","options":"Warehouse","width":190},{"label":_("Audited Transfers"),"fieldname":"audited_transfers","fieldtype":"Int","width":105},{"label":_("Clean"),"fieldname":"clean_count","fieldtype":"Int","width":70},{"label":_("Variance"),"fieldname":"variance_count","fieldtype":"Int","width":75},{"label":_("Pending"),"fieldname":"pending_count","fieldtype":"Int","width":75},{"label":_("Qty Sent"),"fieldname":"qty_sent","fieldtype":"Float","precision":3,"width":90},{"label":_("Qty Received"),"fieldname":"qty_received","fieldtype":"Float","precision":3,"width":100},{"label":_("ABS Variance"),"fieldname":"abs_variance","fieldtype":"Float","precision":3,"width":100},{"label":_("Ignored Qty"),"fieldname":"ignored_qty","fieldtype":"Float","precision":3,"width":90},{"label":_("Variance %"),"fieldname":"variance_pct","fieldtype":"Percent","width":90}]
def get_data(f):
    recs=frappe.get_list("Stock Transfer Audit Record",filters={"docstatus":["in",[1,2]]},fields=["name","receive_stock","target_warehouse","audit_result","processing_status","total_sent_qty","total_received_qty","total_abs_variance_qty"],limit_page_length=0)
    if not recs:return []
    receives=[r.receive_stock for r in recs if r.receive_stock]; dates={}
    for row in frappe.get_all("Stock Entry",filters={"name":["in",receives]},fields=["name","posting_date"],limit_page_length=0):dates[row.name]=row.posting_date
    selected=[r for r in recs if r.receive_stock in dates and getdate(f.from_date)<=getdate(dates[r.receive_stock])<=getdate(f.to_date) and (not f.target_warehouse or r.target_warehouse==f.target_warehouse)]
    if not selected:return []
    names=[r.name for r in selected]; ignored={}
    for row in frappe.get_all("Stock Transfer Audit Item",filters={"parent":["in",names],"parenttype":"Stock Transfer Audit Record","action":"Ignore"},fields=["parent","discrepancy_qty"],limit_page_length=0):ignored[row.parent]=flt(ignored.get(row.parent))+abs(flt(row.discrepancy_qty))
    G={}
    for r in selected:
        k=r.target_warehouse or "Unknown"; g=G.setdefault(k,{"target_warehouse":r.target_warehouse,"audited_transfers":0,"clean_count":0,"variance_count":0,"pending_count":0,"qty_sent":0.0,"qty_received":0.0,"abs_variance":0.0,"ignored_qty":0.0})
        g["audited_transfers"]+=1; g["clean_count"]+=1 if r.audit_result=="Clean" else 0; g["variance_count"]+=1 if r.audit_result=="Variance" else 0; g["pending_count"]+=1 if r.processing_status=="Pending" else 0
        g["qty_sent"]+=flt(r.total_sent_qty); g["qty_received"]+=flt(r.total_received_qty); g["abs_variance"]+=flt(r.total_abs_variance_qty); g["ignored_qty"]+=flt(ignored.get(r.name))
    out=[]
    for g in G.values(): g["variance_pct"]=(g["abs_variance"]/g["qty_sent"]*100) if g["qty_sent"] else 0; out.append(g)
    return sorted(out,key=lambda x:(-x["variance_pct"],-x["abs_variance"],x["target_warehouse"] or ""))
