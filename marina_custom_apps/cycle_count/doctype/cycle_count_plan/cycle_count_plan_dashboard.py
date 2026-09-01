from frappe import _


def get_data():
    return {
        "fieldname": "cycle_count_plan",
        "transactions": [
            {
                "label": _("Cycle Count"),
                "items": ["Store Cycle Count"],
            }
        ],
    }
