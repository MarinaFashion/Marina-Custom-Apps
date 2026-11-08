"""Retire two obsolete Design permission navigation pages, without deleting roles.

The workspace now links directly to the three maintained DocTypes. This patch
is idempotent and intentionally does not alter workspace visibility or team
membership data.
"""

import frappe


def execute():
    for name in ("design-security-permissions", "design-role-hierarchy"):
        if frappe.db.exists("Page", name):
            frappe.delete_doc(
                "Page", name, ignore_permissions=True, force=True
            )
    frappe.clear_cache()
