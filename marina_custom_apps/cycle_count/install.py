import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
CUSTOM_FIELDS={"Stock Reconciliation":[{"fieldname":"custom_store_cycle_count","label":"Store Cycle Count","fieldtype":"Link","options":"Store Cycle Count","insert_after":"company","read_only":1,"no_copy":1}]}
NUMBER_CARDS=[("Pending Cycle Counts","marina_custom_apps.cycle_count.kpi_service.pending_cycle_counts"),("Never Counted Coverage","marina_custom_apps.cycle_count.kpi_service.never_counted_coverage"),("Cycle Count ABS Variance Qty","marina_custom_apps.cycle_count.kpi_service.total_abs_variance_qty"),("Cycle Count Inventory Accuracy","marina_custom_apps.cycle_count.kpi_service.average_inventory_accuracy")]
def after_install():
    if not frappe.db.exists("Role","Cycle Count Store User"): frappe.get_doc({"doctype":"Role","role_name":"Cycle Count Store User"}).insert(ignore_permissions=True)
    create_custom_fields(CUSTOM_FIELDS,update=True);_cards()
def after_migrate(): after_install()
def _cards():
    if not frappe.db.exists("DocType","Number Card"): return
    for label,method in NUMBER_CARDS:
        v={"label":label,"type":"Custom","method":method,"is_public":1,"show_percentage_stats":0}
        if frappe.db.exists("Number Card",label): frappe.db.set_value("Number Card",label,v,update_modified=False)
        else: frappe.get_doc({"doctype":"Number Card","name":label,**v}).insert(ignore_permissions=True)
