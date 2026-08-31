import frappe

def on_submit(doc, method=None):
    name = getattr(doc, "custom_store_cycle_count", None)
    if name and frappe.db.exists("Store Cycle Count", name):
        frappe.db.set_value("Store Cycle Count", name, "status", "Reconciled", update_modified=False)

def on_cancel(doc, method=None):
    name = getattr(doc, "custom_store_cycle_count", None)
    if name and frappe.db.exists("Store Cycle Count", name):
        frappe.db.set_value("Store Cycle Count", name, "status", "Reconciliation Created", update_modified=False)
