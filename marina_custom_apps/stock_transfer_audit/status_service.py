import frappe
from frappe.utils import flt

ACTION_MOVE_TO_SOURCE = "Move to Source"
ACTION_MOVE_TO_TARGET = "Move to Target"
TRANSFER_BETWEEN = "Transfer Between"


def _submitted_correction(record_name, direction):
    return bool(
        frappe.db.exists(
            "Stock Entry",
            {
                "custom_stock_transfer_audit_record": record_name,
                "custom_audit_correction_direction": direction,
                "stock_entry_type": TRANSFER_BETWEEN,
                "docstatus": 1,
            },
        )
    )


def _required_corrections(record):
    needs_source = False
    needs_target = False

    for row in record.items or []:
        variance = flt(row.discrepancy_qty)
        if variance > 0 and row.action == ACTION_MOVE_TO_SOURCE:
            needs_source = True
        elif variance < 0 and row.action == ACTION_MOVE_TO_TARGET:
            needs_target = True

    return needs_source, needs_target


def get_record_processing_status(record):
    if record.record_type == "Legacy / Previous Process":
        return "Completed"

    if record.audit_result == "Clean":
        return "Completed"

    if record.audit_result != "Variance":
        return "Pending"

    needs_source, needs_target = _required_corrections(record)

    if needs_source and not _submitted_correction(record.name, ACTION_MOVE_TO_SOURCE):
        return "Pending"

    if needs_target and not _submitted_correction(record.name, ACTION_MOVE_TO_TARGET):
        return "Pending"

    # A user override can legitimately mean no ledger correction is needed.
    # In that case, Generate Correction marks the record as processed.
    if not needs_source and not needs_target:
        return "Completed" if record.resolution_method == "Audit Correction" else "Pending"

    return "Completed"


def update_record_status(record_name):
    if not record_name or not frappe.db.exists("Stock Transfer Audit Record", record_name):
        return None

    record = frappe.get_doc("Stock Transfer Audit Record", record_name)
    status = get_record_processing_status(record)

    if record.processing_status != status:
        frappe.db.set_value(
            "Stock Transfer Audit Record",
            record.name,
            "processing_status",
            status,
            update_modified=False,
        )

    if record.audit_run:
        update_run_status(record.audit_run)

    return status


def update_run_status(run_name):
    if not run_name or not frappe.db.exists("Stock Transfer Audit Run", run_name):
        return None

    docstatus = frappe.db.get_value("Stock Transfer Audit Run", run_name, "docstatus")

    if docstatus == 0:
        status = "Draft"
    else:
        rows = frappe.get_all(
            "Stock Transfer Audit Record",
            filters={"audit_run": run_name},
            fields=["processing_status"],
            limit_page_length=0,
        )
        status = (
            "Completed"
            if rows and all(r.processing_status == "Completed" for r in rows)
            else "Pending"
        )

    frappe.db.set_value(
        "Stock Transfer Audit Run",
        run_name,
        "run_status",
        status,
        update_modified=False,
    )
    return status


def on_stock_entry_submit(doc, method=None):
    record_name = doc.get("custom_stock_transfer_audit_record")
    if record_name:
        update_record_status(record_name)


def on_stock_entry_cancel(doc, method=None):
    record_name = doc.get("custom_stock_transfer_audit_record")
    if record_name:
        update_record_status(record_name)


def on_stock_entry_trash(doc, method=None):
    record_name = doc.get("custom_stock_transfer_audit_record")
    if record_name:
        # Deleting the correction is allowed; its parent Audit Record remains.
        # The status will revert to Pending after the delete transaction.
        frappe.enqueue(
            "marina_custom_apps.stock_transfer_audit.status_service.update_record_status",
            queue="short",
            enqueue_after_commit=True,
            record_name=record_name,
        )
