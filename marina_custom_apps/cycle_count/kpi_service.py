import frappe
from frappe.utils import flt
@frappe.whitelist()
def pending_cycle_counts(): return frappe.db.count("Store Cycle Count",{"docstatus":0,"status":["not in",["Reconciled","Cancelled"]]})
@frappe.whitelist()
def never_counted_coverage(): return frappe.db.count("Cycle Count Coverage",{"last_count_date":["is","not set"]})
@frappe.whitelist()
def total_abs_variance_qty(): return flt(frappe.db.sql("select coalesce(sum(abs(variance_qty)),0) from `tabStore Cycle Count Item` where counted=1")[0][0])
@frappe.whitelist()
def average_inventory_accuracy(): return flt(frappe.db.sql("select coalesce(avg(last_inventory_accuracy_percent),100) from `tabCycle Count Coverage` where last_count_date is not null")[0][0])
