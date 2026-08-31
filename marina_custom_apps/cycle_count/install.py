import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
    "Stock Reconciliation": [
        {
            "fieldname": "custom_store_cycle_count",
            "label": "Store Cycle Count",
            "fieldtype": "Link",
            "options": "Store Cycle Count",
            "insert_after": "company",
            "read_only": 1,
            "no_copy": 1,
        }
    ]
}

def after_install():
    if not frappe.db.exists("Role", "Cycle Count Store User"):
        frappe.get_doc({"doctype": "Role", "role_name": "Cycle Count Store User"}).insert(ignore_permissions=True)
    create_custom_fields(CUSTOM_FIELDS, update=True)

def after_migrate():
    after_install()
