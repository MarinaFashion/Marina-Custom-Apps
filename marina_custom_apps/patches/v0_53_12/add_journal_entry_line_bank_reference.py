import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    # Native accounting child-row field: no change to the standard GL posting rules.
    create_custom_fields(
        {
            "Journal Entry Account": [
                {
                    "fieldname": "custom_bank_reference_number",
                    "label": "Bank Reference Number",
                    "fieldtype": "Data",
                    "insert_after": "user_remark",
                    "description": "",
                    "in_list_view": 1,
                }
            ]
        },
        update=True,
    )
