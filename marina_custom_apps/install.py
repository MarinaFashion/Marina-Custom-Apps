from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


STOCK_ENTRY_FIELDS = [
    {
        "fieldname": "custom_transfer_control_section",
        "label": "Marina Stock Transfer Control",
        "fieldtype": "Section Break",
        "insert_after": "to_warehouse",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_intended_final_warehouse",
        "label": "Intended Final Warehouse",
        "fieldtype": "Link",
        "options": "Warehouse",
        "insert_after": "custom_transfer_control_section",
        "read_only": 1,
        "no_copy": 1,
        "description": (
            "Physical destination derived from the selected transit warehouse "
            "for Send Stock."
        ),
    },
    {
        "fieldname": "custom_receiving_method",
        "label": "Receiving Method",
        "fieldtype": "Select",
        "options": "\nNormal Receiving\nManual / Barcode Receiving",
        "insert_after": "custom_intended_final_warehouse",
        "read_only": 1,
        "no_copy": 1,
        "description": (
            "Selected once on a Draft Receive Stock and then locked."
        ),
    },
    {
        "fieldname": "custom_receive_via_end_transit",
        "label": "Created via End Transit",
        "fieldtype": "Check",
        "insert_after": "custom_receiving_method",
        "read_only": 1,
        "no_copy": 1,
        "hidden": 1,
        "description": (
            "Internal control flag. Receive Stock must be created through "
            "the controlled End Transit process."
        ),
    },
]

STOCK_ENTRY_DETAIL_FIELDS = [
    {
        "fieldname": "custom_transfer_reconciliation_section",
        "label": "Transfer Reconciliation",
        "fieldtype": "Section Break",
        "insert_after": "qty",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_sent_qty",
        "label": "Sent Qty",
        "fieldtype": "Float",
        "insert_after": "custom_transfer_reconciliation_section",
        "read_only": 1,
        "no_copy": 1,
        "precision": "3",
        "description": "Quantity recorded on the original Send Stock line.",
    },
    {
        "fieldname": "custom_actual_received_qty",
        "label": "Actual Received Qty",
        "fieldtype": "Float",
        "insert_after": "custom_sent_qty",
        "no_copy": 1,
        "precision": "3",
        "description": (
            "Physical quantity confirmed by the receiver. This is the "
            "receiver's statement of fact, not necessarily the ledger-posting Qty."
        ),
    },
    {
        "fieldname": "custom_discrepancy_qty",
        "label": "Discrepancy Qty",
        "fieldtype": "Float",
        "insert_after": "custom_actual_received_qty",
        "read_only": 1,
        "no_copy": 1,
        "precision": "3",
        "description": "Sent Qty - Actual Received Qty. Positive = shortage; negative = excess.",
    },
    {
        "fieldname": "custom_unexpected_item",
        "label": "Unexpected Item",
        "fieldtype": "Check",
        "insert_after": "custom_discrepancy_qty",
        "read_only": 1,
        "no_copy": 1,
        "description": "Checked when the item did not exist on the original Send Stock.",
    },
    {
        "fieldname": "custom_original_send_stock_detail",
        "label": "Original Send Stock Detail",
        "fieldtype": "Data",
        "insert_after": "custom_unexpected_item",
        "read_only": 1,
        "no_copy": 1,
        "hidden": 1,
        "description": "Name of the originating Stock Entry Detail row for traceability.",
    },
]

CUSTOM_FIELDS = {
    "Stock Entry": STOCK_ENTRY_FIELDS,
    "Stock Entry Detail": STOCK_ENTRY_DETAIL_FIELDS,
}


def after_install():
    _ensure_custom_fields()


def after_migrate():
    _ensure_custom_fields()
    _cleanup_legacy_original_send_stock_field()


def _ensure_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, update=True)


def _cleanup_legacy_original_send_stock_field():
    """Migrate old duplicate reference then remove its Custom Field metadata."""
    import frappe

    fieldname = "custom_original_send_stock"
    custom_field_name = f"Stock Entry-{fieldname}"

    if frappe.db.has_column("Stock Entry", fieldname):
        frappe.db.sql(
            f"""
            update `tabStock Entry`
            set outgoing_stock_entry = {fieldname}
            where ifnull(outgoing_stock_entry, ) = 
              and ifnull({fieldname}, ) != 
            """
        )

    if frappe.db.exists("Custom Field", custom_field_name):
        frappe.delete_doc(
            "Custom Field",
            custom_field_name,
            ignore_permissions=True,
            force=True,
        )
        frappe.clear_cache(doctype="Stock Entry")
