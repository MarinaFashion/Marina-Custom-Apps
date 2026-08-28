import frappe
from frappe.utils import flt

ACTION_MOVE_TO_SOURCE = "Move to Source"
ACTION_MOVE_TO_TARGET = "Move to Target"
ACTION_IGNORE = "Ignore"
TRANSFER_BETWEEN = "Transfer Between"

def _submitted_correction(record_name, direction):
    return bool(frappe.db.exists("Stock Entry", {
        "custom_stock_transfer_audit_record": record_name,
        "custom_audit_correction_direction": direction,
        "stock_entry_type": TRANSFER_BETWEEN,
        "docstatus": 1,
    }))

def get_record_processing_status(record):
    if record.docstatus == 2:
        return "Cancelled"
    if record.record_type == "Legacy / Previous Process" or record.audit_result == "Clean":
        return "Completed"
    if record.audit_result != "Variance":
        return "Pending"
    need_source = need_target = False
    for row in record.items or []:
        variance = flt(row.discrepancy_qty)
        if row.action == ACTION_IGNORE:
            continue
        if variance > 0 and row.action == ACTION_MOVE_TO_SOURCE:
            need_source = True
        elif variance < 0 and row.action == ACTION_MOVE_TO_TARGET:
            need_target = True
    if need_source and not _submitted_correction(record.name, ACTION_MOVE_TO_SOURCE):
        return "Pending"
    if need_target and not _submitted_correction(record.name, ACTION_MOVE_TO_TARGET):
        return "Pending"
    return "Completed"

def update_record_status(record_name):
    if not record_name or not frappe.db.exists("Stock Transfer Audit Record", record_name):
        return None
    record = frappe.get_doc("Stock Transfer Audit Record", record_name)
    status = get_record_processing_status(record)
    if record.processing_status != status:
        frappe.db.set_value("Stock Transfer Audit Record", record.name, "processing_status", status, update_modified=False)
    if record.audit_run:
        update_run_status(record.audit_run)
    return status

def update_run_status(run_name):
    if not run_name or not frappe.db.exists("Stock Transfer Audit Run", run_name):
        return None
    docstatus = frappe.db.get_value("Stock Transfer Audit Run", run_name, "docstatus")
    if docstatus == 0:
        status = "Draft"
    elif docstatus == 2:
        status = "Cancelled"
    else:
        rows = frappe.get_all("Stock Transfer Audit Record", filters={"audit_run": run_name}, fields=["processing_status"], limit_page_length=0)
        status = "Completed" if rows and all(r.processing_status == "Completed" for r in rows) else "Pending"
    frappe.db.set_value("Stock Transfer Audit Run", run_name, "run_status", status, update_modified=False)
    return status

def on_stock_entry_submit(doc, method=None):
    if doc.get("custom_stock_transfer_audit_record"):
        update_record_status(doc.custom_stock_transfer_audit_record)

def on_stock_entry_cancel(doc, method=None):
    if doc.get("custom_stock_transfer_audit_record"):
        update_record_status(doc.custom_stock_transfer_audit_record)

def on_stock_entry_trash(doc, method=None):
    if doc.get("custom_stock_transfer_audit_record"):
        frappe.enqueue(
            "marina_custom_apps.stock_transfer_audit.status_service.update_record_status",
            queue="short", enqueue_after_commit=True,
            record_name=doc.custom_stock_transfer_audit_record,
        )
