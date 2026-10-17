from __future__ import annotations

import frappe


SELECT_OPTIONS = {
    ("POS Bank Statement Reconciliation", "status"): "Draft\nCompleted",
    ("POS Bank Settlement", "status"): (
        "ERP Settlement Only\nPartial\nAmount Difference\nFully Reconciled"
    ),
    ("POS Bank Settlement Statement Match", "component"): "Gross\nCommission\nVAT",
    ("POS Bank Settlement Statement Match", "direction"): "Deposit\nWithdrawal",
    ("POS Bank Settlement Statement Match", "match_status"): "Parsed\nMatched\nDifference",
    ("POS Bank Statement Code Mapping", "component"): "Gross\nCommission\nVAT",
}


def execute():
    touched = set()

    for (parent, fieldname), options in SELECT_OPTIONS.items():
        name = frappe.db.get_value(
            "DocField",
            {"parent": parent, "fieldname": fieldname},
            "name",
        )
        if not name:
            continue

        frappe.db.set_value(
            "DocField",
            name,
            "options",
            options,
            update_modified=False,
        )
        touched.add(parent)

    for doctype in touched:
        frappe.clear_cache(doctype=doctype)
