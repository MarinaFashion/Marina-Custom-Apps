import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.nestedset import get_descendants_of
from marina_custom_apps.cycle_count.utils import primary_barcodes, sizes, require_stock_manager

class CycleCountPlan(Document):
    def validate(self):
        require_stock_manager()
        wh=[r.warehouse for r in self.stores]
        st=[r.item_template for r in self.styles]
        if len(wh) != len(set(wh)):
            frappe.throw(_("A store warehouse can only appear once."))
        if len(st) != len(set(st)):
            frappe.throw(_("A style can only appear once."))

    @frappe.whitelist()
    def load_styles(self):
        require_stock_manager()
        if self.selection_mode != "Item Group" or not self.item_group:
            frappe.throw(_("Select Item Group mode and an Item Group first."))
        groups=[self.item_group] + get_descendants_of("Item Group", self.item_group)
        rows=frappe.get_all("Item", filters={"disabled":0,"item_group":["in",groups],"has_variants":1},
                            fields=["name","item_name"], order_by="name asc", limit_page_length=0)
        self.set("styles", [])
        for r in rows:
            self.append("styles", {"item_template":r.name,"item_name":r.item_name})
        self.save()
        return len(rows)

    @frappe.whitelist()
    def generate_store_counts(self):
        require_stock_manager()
        if not self.stores or not self.styles:
            frappe.throw(_("Add at least one store and one style."))
        styles=[r.item_template for r in self.styles]
        items=frappe.get_all("Item", filters={"disabled":0,"variant_of":["in",styles]},
                             fields=["name","item_name","variant_of"], order_by="variant_of asc, name asc", limit_page_length=0)
        items += frappe.get_all("Item", filters={"disabled":0,"name":["in",styles],"has_variants":0},
                                fields=["name","item_name","variant_of"], limit_page_length=0)
        if not items:
            frappe.throw(_("No active variants/items found for the selected styles."))
        codes=[r.name for r in items]
        bc=primary_barcodes(codes); sz=sizes(codes)
        created=[]
        for s in self.stores:
            if s.store_cycle_count and frappe.db.exists("Store Cycle Count", s.store_cycle_count):
                continue
            meta=frappe.db.get_value("Warehouse", s.warehouse, ["disabled","is_group","company"], as_dict=True)
            if not meta or meta.disabled or meta.is_group or meta.company != self.company:
                frappe.throw(_("Warehouse {0} must be an active non-group warehouse for this company.").format(s.warehouse))
            d=frappe.new_doc("Store Cycle Count")
            d.update({"cycle_count_plan":self.name,"company":self.company,"warehouse":s.warehouse,
                      "assigned_to":s.assigned_to,"count_date":self.count_date,"count_window":self.count_window,"status":"Assigned"})
            for i in items:
                d.append("items", {"item_code":i.name,"item_name":i.item_name,"item_template":i.variant_of or i.name,
                                   "size":sz.get(i.name),"barcode":bc.get(i.name)})
            d.insert(ignore_permissions=True)
            s.db_set("store_cycle_count", d.name, update_modified=False)
            created.append(d.name)
        self.db_set("generated_count_count", len([r for r in self.stores if r.store_cycle_count]), update_modified=False)
        self.db_set("status","Counts Generated",update_modified=False)
        return created
