"""Add optional HR-managed exemption flag; leave existing employees unchanged."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Employee": [{
            "fieldname": "custom_exclude_from_leave_accrual",
            "label": "Exclude from Automatic Paid Leave Accrual",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "custom_leave_period",
            "description": (
                "Exclude this employee from Marina paid leave accrual and "
                "historical reconciliation. HR can use this for owners, "
                "remote employees, or other approved exemptions."
            ),
        }]
    }, update=True)
