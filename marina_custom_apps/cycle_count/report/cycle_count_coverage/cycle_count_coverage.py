import frappe
from frappe import _
def execute(filters=None):
    filters=filters or {}; cols=[{"label":_("Store"),"fieldname":"store_warehouse","fieldtype":"Link","options":"Warehouse","width":190},{"label":_("Style"),"fieldname":"item_template","fieldtype":"Link","options":"Item","width":150},{"label":_("Last Selected"),"fieldname":"last_selected_date","fieldtype":"Date","width":110},{"label":_("Last Count"),"fieldname":"last_count_date","fieldtype":"Date","width":110},{"label":_("Counts"),"fieldname":"number_of_counts","fieldtype":"Int","width":80},{"label":_("Status"),"fieldname":"last_count_status","fieldtype":"Data","width":130},{"label":_("Variance Qty"),"fieldname":"last_variance_qty","fieldtype":"Float","width":100},{"label":_("Accuracy %"),"fieldname":"last_inventory_accuracy_percent","fieldtype":"Percent","width":100}]
    f={k:filters[k] for k in ("company","store_warehouse","item_template") if filters.get(k)}
    return cols,frappe.get_all("Cycle Count Coverage",filters=f,fields=[c["fieldname"] for c in cols],order_by="last_count_date asc, store_warehouse asc",limit_page_length=0)
