import frappe
from frappe.utils import flt, getdate, nowdate

def _classification(template):
    settings=frappe.get_single("DC Dispatch Settings"); meta=frappe.get_meta("Item")
    fmap={"item_name":"item_name","item_year":"item_year","season":"season","collection":"collection","drop":"custom_drop","main_group":settings.item_main_group_field}
    valid=[v for v in fmap.values() if v and meta.get_field(v)]
    row=frappe.db.get_value("Item",template,valid,as_dict=True) or {}
    return {k:row.get(v) for k,v in fmap.items() if v in valid}

def _upsert(company,warehouse,template,values):
    name=frappe.db.get_value("Cycle Count Coverage",{"company":company,"store_warehouse":warehouse,"item_template":template},"name")
    vals={**_classification(template),**values}
    if name:
        frappe.db.set_value("Cycle Count Coverage",name,vals,update_modified=False); return name
    doc=frappe.get_doc({"doctype":"Cycle Count Coverage","company":company,"store_warehouse":warehouse,"item_template":template,**vals})
    doc.insert(ignore_permissions=True); return doc.name

def mark_selected(plan):
    dt=getdate(plan.count_date or nowdate())
    for s in plan.stores:
        for i in plan.styles:
            _upsert(plan.company,s.warehouse,i.item_template,{"last_selected_date":dt,"last_cycle_count_plan":plan.name,"last_count_status":"Selected / Pending"})

def mark_completed(count):
    agg={}
    for r in count.items:
        t=r.item_template or r.item_code; b=agg.setdefault(t,{"vq":0.0,"vv":0.0,"sq":0.0})
        b["vq"]+=flt(r.variance_qty); b["vv"]+=flt(r.variance_value); b["sq"]+=abs(flt(r.system_qty))
    dt=getdate(count.count_completed_on or nowdate())
    for t,b in agg.items():
        old=frappe.db.get_value(
            "Cycle Count Coverage",
            {"company":count.company,"store_warehouse":count.warehouse,"item_template":t},
            ["first_count_date","number_of_counts","last_store_cycle_count"],
            as_dict=True,
        ) or {}
        acc=100.0 if not b["sq"] else max(0.0,100.0-abs(b["vq"])*100.0/b["sq"])
        already_recorded = old.get("last_store_cycle_count") == count.name
        vals={
            "last_count_date":dt,
            "last_cycle_count_plan":count.cycle_count_plan,
            "last_store_cycle_count":count.name,
            "last_count_status":"Completed",
            "last_variance_qty":b["vq"],
            "last_variance_value":b["vv"],
            "last_inventory_accuracy_percent":acc,
            "number_of_counts":int(old.get("number_of_counts") or 0) + (0 if already_recorded else 1),
        }
        if not old.get("first_count_date"): vals["first_count_date"]=dt
        _upsert(count.company,count.warehouse,t,vals)
