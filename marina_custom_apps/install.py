from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

STOCK_ENTRY_FIELDS = [
    {"fieldname":"custom_transfer_control_section","label":"Marina Stock Transfer Control","fieldtype":"Section Break","insert_after":"to_warehouse","collapsible":1},
    {"fieldname":"custom_intended_final_warehouse","label":"Intended Final Warehouse","fieldtype":"Link","options":"Warehouse","insert_after":"custom_transfer_control_section","read_only":1,"no_copy":1},
    {"fieldname":"custom_receiving_method","label":"Receiving Method","fieldtype":"Select","options":"\nNormal Receiving\nManual / Barcode Receiving","insert_after":"custom_intended_final_warehouse","read_only":1,"no_copy":1},
    {"fieldname":"custom_receive_via_end_transit","label":"Created via End Transit","fieldtype":"Check","insert_after":"custom_receiving_method","read_only":1,"no_copy":1,"hidden":1},
    {"fieldname":"custom_stock_transfer_audit_record","label":"Stock Transfer Audit Record","fieldtype":"Link","options":"Stock Transfer Audit Record","insert_after":"custom_receive_via_end_transit","read_only":1,"no_copy":1,"hidden":1},
    {"fieldname":"custom_audit_correction_direction","label":"Audit Correction Direction","fieldtype":"Select","options":"\nMove to Source\nMove to Target","insert_after":"custom_stock_transfer_audit_record","read_only":1,"no_copy":1,"hidden":1},
    {"fieldname":"custom_unexpected_received_items","label":"Unexpected Received Items","fieldtype":"Table","options":"Unexpected Received Item","insert_after":"items","read_only":1,"no_copy":1},
    {"fieldname":"custom_transfer_totals_section","label":"Quantity Totals","fieldtype":"Section Break","insert_after":"custom_unexpected_received_items"},
    {"fieldname":"custom_total_qty","label":"Total Qty","fieldtype":"Float","insert_after":"custom_transfer_totals_section","read_only":1,"no_copy":1,"precision":"3"},
    {"fieldname":"custom_total_sent_qty","label":"Total Sent Qty","fieldtype":"Float","insert_after":"custom_total_qty","read_only":1,"no_copy":1,"precision":"3"},
    {"fieldname":"custom_total_received_qty","label":"Total Received Qty","fieldtype":"Float","insert_after":"custom_total_sent_qty","read_only":1,"no_copy":1,"precision":"3"},
    {"fieldname":"custom_totals_column_break","fieldtype":"Column Break","insert_after":"custom_total_received_qty"},
    {"fieldname":"custom_total_variance_qty","label":"Total Variance Qty","fieldtype":"Float","insert_after":"custom_totals_column_break","read_only":1,"no_copy":1,"precision":"3"},
    {"fieldname":"custom_total_abs_variance_qty","label":"Total ABS Variance Qty","fieldtype":"Float","insert_after":"custom_total_variance_qty","read_only":1,"no_copy":1,"precision":"3"},
]
STOCK_ENTRY_DETAIL_FIELDS = [
    {"fieldname":"custom_transfer_reconciliation_section","label":"Transfer Reconciliation","fieldtype":"Section Break","insert_after":"qty","collapsible":1},
    {"fieldname":"custom_actual_received_qty","label":"Actual Received Qty","fieldtype":"Float","insert_after":"custom_transfer_reconciliation_section","no_copy":1,"precision":"3"},
    {"fieldname":"custom_discrepancy_qty","label":"Discrepancy Qty","fieldtype":"Float","insert_after":"custom_actual_received_qty","read_only":1,"no_copy":1,"precision":"3"},
    {"fieldname":"custom_unexpected_item","label":"Unexpected Item","fieldtype":"Check","insert_after":"custom_discrepancy_qty","read_only":1,"no_copy":1},
    {"fieldname":"custom_original_send_stock_detail","label":"Original Send Stock Detail","fieldtype":"Data","insert_after":"custom_unexpected_item","read_only":1,"no_copy":1,"hidden":1},
]
CUSTOM_FIELDS={"Stock Entry":STOCK_ENTRY_FIELDS,"Stock Entry Detail":STOCK_ENTRY_DETAIL_FIELDS}
def after_install(): _ensure_custom_fields()
def after_migrate():
    _ensure_custom_fields(); _cleanup_legacy_original_send_stock_field(); _cleanup_legacy_sent_qty_field(); _backfill_audit_correction_links(); _submit_existing_audit_records(); _refresh_audit_statuses()
def _ensure_custom_fields(): create_custom_fields(CUSTOM_FIELDS,update=True)
def _cleanup_legacy_original_send_stock_field():
    import frappe
    fieldname="custom_original_send_stock"; cf=f"Stock Entry-{fieldname}"
    if frappe.db.has_column("Stock Entry",fieldname):
        frappe.db.sql(f"""update `tabStock Entry` set outgoing_stock_entry = {fieldname} where (outgoing_stock_entry is null or outgoing_stock_entry = %s) and ({fieldname} is not null and {fieldname} != %s)""",("",""))
    if frappe.db.exists("Custom Field",cf): frappe.delete_doc("Custom Field",cf,ignore_permissions=True,force=True); frappe.clear_cache(doctype="Stock Entry")
def _cleanup_legacy_sent_qty_field():
    import frappe
    cf="Stock Entry Detail-custom_sent_qty"
    if frappe.db.exists("Custom Field",cf): frappe.delete_doc("Custom Field",cf,ignore_permissions=True,force=True); frappe.clear_cache(doctype="Stock Entry Detail")
def _backfill_audit_correction_links():
    import frappe
    if not frappe.db.exists("DocType","Stock Transfer Audit Record"): return
    for r in frappe.get_all("Stock Transfer Audit Record",fields=["name","correction_to_source_stock_entry","correction_to_target_stock_entry"],limit_page_length=0):
        for se,direction in ((r.correction_to_source_stock_entry,"Move to Source"),(r.correction_to_target_stock_entry,"Move to Target")):
            if se and frappe.db.exists("Stock Entry",se): frappe.db.set_value("Stock Entry",se,{"custom_stock_transfer_audit_record":r.name,"custom_audit_correction_direction":direction},update_modified=False)
def _submit_existing_audit_records():
    import frappe
    if not frappe.db.exists("DocType","Stock Transfer Audit Record"): return
    for name in frappe.get_all("Stock Transfer Audit Record",filters={"docstatus":0},pluck="name",limit_page_length=0):
        doc=frappe.get_doc("Stock Transfer Audit Record",name); doc.flags.ignore_permissions=True; doc.submit()
def _refresh_audit_statuses():
    import frappe
    if not frappe.db.exists("DocType","Stock Transfer Audit Record"): return
    from marina_custom_apps.stock_transfer_audit.status_service import update_record_status, update_run_status
    runs=set()
    for r in frappe.get_all("Stock Transfer Audit Record",fields=["name","audit_run"],limit_page_length=0):
        update_record_status(r.name)
        if r.audit_run: runs.add(r.audit_run)
    for run in runs: update_run_status(run)
