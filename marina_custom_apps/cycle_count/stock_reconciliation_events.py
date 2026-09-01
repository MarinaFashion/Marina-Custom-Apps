import frappe
from marina_custom_apps.cycle_count.coverage import mark_completed
def on_submit(doc,method=None):
    if not doc.custom_store_cycle_count:return
    c=frappe.get_doc("Store Cycle Count",doc.custom_store_cycle_count);c.db_set("status","Reconciled",update_modified=False);mark_completed(c)
def on_cancel(doc,method=None):
    if not doc.custom_store_cycle_count:return
    frappe.db.set_value("Store Cycle Count",doc.custom_store_cycle_count,"status","Reconciliation Created",update_modified=False)
