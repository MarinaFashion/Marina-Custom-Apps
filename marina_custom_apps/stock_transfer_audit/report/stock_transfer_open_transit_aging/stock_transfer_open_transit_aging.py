import frappe
from frappe import _
from frappe.utils import cint,date_diff,flt,getdate,today
def execute(filters=None):
    f=frappe._dict(filters or {}); return get_columns(),get_data(f)
def get_columns():
    return [{"label":_("Status"),"fieldname":"aging_status","fieldtype":"Data","width":90},{"label":_("Age Days"),"fieldname":"age_days","fieldtype":"Int","width":80},{"label":_("Send Stock"),"fieldname":"send_stock","fieldtype":"Link","options":"Stock Entry","width":150},{"label":_("Posting Date"),"fieldname":"posting_date","fieldtype":"Date","width":100},{"label":_("Source Warehouse"),"fieldname":"source_warehouse","fieldtype":"Link","options":"Warehouse","width":180},{"label":_("Transit Warehouse"),"fieldname":"transit_warehouse","fieldtype":"Link","options":"Warehouse","width":180},{"label":_("Target Warehouse"),"fieldname":"target_warehouse","fieldtype":"Link","options":"Warehouse","width":180},{"label":_("Qty Sent"),"fieldname":"qty_sent","fieldtype":"Float","precision":3,"width":95},{"label":_("Stock Value"),"fieldname":"stock_value","fieldtype":"Currency","width":110},{"label":_("Receive Draft"),"fieldname":"receive_draft","fieldtype":"Link","options":"Stock Entry","width":150},{"label":_("Created By"),"fieldname":"owner","fieldtype":"Link","options":"User","width":160}]
def get_data(f):
    sf={"docstatus":1,"stock_entry_type":"Send Stock"}
    if f.company: sf["company"]=f.company
    if f.source_warehouse: sf["from_warehouse"]=f.source_warehouse
    if f.target_warehouse: sf["custom_intended_final_warehouse"]=f.target_warehouse
    sends=frappe.get_list("Stock Entry",filters=sf,fields=["name","posting_date","from_warehouse","to_warehouse","custom_intended_final_warehouse","owner"],order_by="posting_date asc, creation asc",limit_page_length=0)
    if not sends:return []
    names=[r.name for r in sends]; submitted=set(frappe.get_all("Stock Entry",filters={"docstatus":1,"stock_entry_type":"Receive Stock","outgoing_stock_entry":["in",names]},pluck="outgoing_stock_entry",limit_page_length=0))
    drafts={};
    for r in frappe.get_all("Stock Entry",filters={"docstatus":0,"stock_entry_type":"Receive Stock","outgoing_stock_entry":["in",names]},fields=["name","outgoing_stock_entry"],order_by="creation desc",limit_page_length=0): drafts.setdefault(r.outgoing_stock_entry,r.name)
    qty={}; value={}
    for d in frappe.get_all("Stock Entry Detail",filters={"parent":["in",names],"parenttype":"Stock Entry"},fields=["parent","qty","basic_rate"],limit_page_length=0): qty[d.parent]=flt(qty.get(d.parent))+flt(d.qty); value[d.parent]=flt(value.get(d.parent))+flt(d.qty)*flt(d.basic_rate)
    out=[]; min_age=max(cint(f.minimum_age_days),0); overdue=max(cint(f.overdue_after_days),0); now=getdate(today())
    for r in sends:
        if r.name in submitted: continue
        age=max(date_diff(now,getdate(r.posting_date)),0)
        if age<min_age: continue
        out.append({"aging_status":"Overdue" if age>overdue else "Open","age_days":age,"send_stock":r.name,"posting_date":r.posting_date,"source_warehouse":r.from_warehouse,"transit_warehouse":r.to_warehouse,"target_warehouse":r.custom_intended_final_warehouse,"qty_sent":qty.get(r.name,0),"stock_value":value.get(r.name,0),"receive_draft":drafts.get(r.name),"owner":r.owner})
    return sorted(out,key=lambda x:(-x["age_days"],x["posting_date"],x["send_stock"]))
