from frappe import _


def get_data():
    return {
        "fieldname": "audit_run",
        "transactions": [
            {
                "label": _("Audit"),
                "items": ["Stock Transfer Audit Record"],
            }
        ],
    }
