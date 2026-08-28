from frappe import _


def get_data():
    return {
        "fieldname": "stock_transfer_audit_record",
        "non_standard_fieldnames": {
            "Stock Entry": "custom_stock_transfer_audit_record",
        },
        "transactions": [
            {
                "label": _("Correction"),
                "items": ["Stock Entry"],
            }
        ],
    }
