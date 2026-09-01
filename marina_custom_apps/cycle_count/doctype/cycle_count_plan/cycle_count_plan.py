import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff,getdate,nowdate
from marina_custom_apps.cycle_count.coverage import mark_selected
from marina_custom_apps.cycle_count.store_assignment import assignment_payload,parse_assignments,validate_assignment
from marina_custom_apps.cycle_count.utils import primary_barcodes,require_stock_manager,sizes
FILTER_FIELDS=("item_year","season","collection","drop","main_group")

class CycleCountPlan(Document):
    def validate(self):
        require_stock_manager()
        wh=[r.warehouse for r in self.stores]; st=[r.item_template for r in self.styles]
        if len(wh)!=len(set(wh)): frappe.throw(_("A store warehouse can only appear once."))
        if len(st)!=len(set(st)): frappe.throw(_("A style can only appear once."))
        for r in self.stores:
            if r.assigned_to: validate_assignment(r.warehouse,r.assigned_to)

    @frappe.whitelist()
    def load_eligible_items(self):
        require_stock_manager(); settings=frappe.get_single("DC Dispatch Settings"); meta=frappe.get_meta("Item")
        fmap={"item_year":"item_year","season":"season","collection":"collection","drop":"custom_drop","main_group":settings.item_main_group_field}
        filters={"disabled":0,"has_variants":1}
        for rf,itf in fmap.items():
            v=getattr(self,rf,None)
            if not v: continue
            if not itf or not meta.get_field(itf): frappe.throw(_("Configured Item filter field {0} does not exist.").format(itf or rf))
            filters[itf]=v
        rows=frappe.get_all("Item",filters=filters,fields=["name","item_name"],order_by="name asc",limit_page_length=0)
        if not rows: frappe.throw(_("No Item Templates matched the selected filters."))
        h=_history(self.company,[r.name for r in rows]); self.set("styles",[])
        for r in rows:
            d=(h.get(r.name) or {}).get("last_count_date")
            self.append("styles",{"item_template":r.name,"item_name":r.item_name,"last_count_date":d,"days_since_last_count":date_diff(getdate(nowdate()),getdate(d)) if d else None,"count_status":"Previously Counted" if d else "Never Counted"})
        self.status="Items Loaded"; self.save(); return {"items":len(self.styles)}

    @frappe.whitelist()
    def load_eligible_stores(self):
        require_stock_manager(); payload=assignment_payload(self.company); existing={r.warehouse:r.assigned_to for r in self.stores}
        self.set("stores",[]); ambiguous=[]; missing=[]
        for r in payload:
            assigned=existing.get(r["warehouse"]) or r["auto_user"]; self.append("stores",{"warehouse":r["warehouse"],"assigned_to":assigned})
            if r["needs_selection"] and not assigned: ambiguous.append({"warehouse":r["warehouse"],"users":r["users"]})
            if r["missing_user"]: missing.append(r["warehouse"])
        self.status="Stores Loaded"; self.save(); return {"stores":len(self.stores),"ambiguous":ambiguous,"missing":missing}

    @frappe.whitelist()
    def assign_store_users(self,assignments=None):
        require_stock_manager(); a=parse_assignments(assignments); rows={r.warehouse:r for r in self.stores}
        for wh,user in a.items():
            if wh not in rows: frappe.throw(_("Warehouse {0} is not in this plan.").format(wh))
            validate_assignment(wh,user); rows[wh].assigned_to=user
        self.save(); return {"assigned":len(a)}

    @frappe.whitelist()
    def generate_store_counts(self):
        require_stock_manager()
        if not self.stores or not self.styles: frappe.throw(_("Load eligible items and stores first."))
        un=[r.warehouse for r in self.stores if not r.assigned_to]
        if un: frappe.throw(_("Assign a Store User before generating counts for: {0}").format(", ".join(un[:50])))
        for r in self.stores: validate_assignment(r.warehouse,r.assigned_to)
        styles=[r.item_template for r in self.styles]
        items=frappe.get_all("Item",filters={"disabled":0,"variant_of":["in",styles]},fields=["name","item_name","variant_of"],order_by="variant_of asc, name asc",limit_page_length=0)
        items+=frappe.get_all("Item",filters={"disabled":0,"name":["in",styles],"has_variants":0},fields=["name","item_name","variant_of"],limit_page_length=0)
        if not items: frappe.throw(_("No active variants/items found."))
        bc=primary_barcodes([r.name for r in items]); sz=sizes([r.name for r in items]); created=[]
        existing_rows=frappe.get_all(
            "Store Cycle Count",
            filters={"cycle_count_plan":self.name,"docstatus":["!=",2]},
            fields=["name","warehouse"],
            limit_page_length=0,
        )
        existing_by_warehouse={r.warehouse:r.name for r in existing_rows}
        for s in self.stores:
            if s.warehouse in existing_by_warehouse: continue
            d=frappe.new_doc("Store Cycle Count"); d.update({"cycle_count_plan":self.name,"company":self.company,"warehouse":s.warehouse,"assigned_to":s.assigned_to,"count_date":self.count_date,"status":"Assigned"})
            for i in items: d.append("items",{"item_code":i.name,"item_name":i.item_name,"item_template":i.variant_of or i.name,"size":sz.get(i.name),"barcode":bc.get(i.name)})
            d.insert(ignore_permissions=True); existing_by_warehouse[s.warehouse]=d.name; created.append(d.name)
        mark_selected(self); self.db_set("generated_count_count",len(existing_by_warehouse),update_modified=False); self.db_set("status","Counts Generated",update_modified=False); return created

@frappe.whitelist()
def get_filter_options(item_year=None,season=None,collection=None,drop=None,main_group=None):
    from marina_custom_apps.dc_dispatch.services.metadata import get_target_filter_options
    data=get_target_filter_options(item_year=item_year,season=season,collection=collection,drop=drop,main_group=main_group,subgroup=None); o=data.get("options") or {}
    return {"options":{k:o.get(k,[]) for k in FILTER_FIELDS},"configuration_errors":data.get("configuration_errors") or []}

def _history(company,templates):
    if not templates or not frappe.db.exists("DocType","Cycle Count Coverage"): return {}
    rows=frappe.get_all("Cycle Count Coverage",filters={"company":company,"item_template":["in",templates],"last_count_date":["is","set"]},fields=["item_template","last_count_date"],order_by="last_count_date desc",limit_page_length=0); out={}
    for r in rows:
        if r.item_template not in out: out[r.item_template]={"last_count_date":r.last_count_date}
    return out
