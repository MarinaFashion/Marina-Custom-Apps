from __future__ import annotations

import frappe


def execute():
    """Preserve old Manual TR records while enabling Manual Group matching."""
    doctype = "Bank Statement Reconciliation Match"
    if not frappe.db.exists("DocType", doctype):
        return
    fieldname = frappe.db.get_value(
        "DocField", {"parent": doctype, "fieldname": "match_type"}, "name"
    )
    if not fieldname:
        return
    frappe.db.set_value(
        "DocField",
        fieldname,
        "options",
        "Auto Reference\nManual TR\nManual Group",
        update_modified=False,
    )
    frappe.clear_cache(doctype=doctype)
