"""Keep Marina business Workspaces independent of the umbrella navigation.

This operation changes only Workspace.parent_page and hides the obsolete
umbrella. It never saves the complete Workspace document, or alters
shortcuts, links, administrator-managed roles, Custom Role overrides,
visibility of an individual workspace, or user access permissions.

Because Workspace.is_hidden is ignored during standard JSON import, this
must execute *after* app-level workspace sync on install/migrate.
"""
import frappe

INDEPENDENT_WORKSPACES = (
    "Marina Calendar",
    "Sales Forecasting",
    "DC Dispatch",
    "Stock Auto Allocation",
    "Stock Transfer Audit",
    "Cycle Count",
    "POS Reconciliation",
    "SOP Management",
    "Permission Manager Dashboard",
    "Marina Design Management",
)


def ensure_independent_workspaces():
    if not frappe.db.exists("DocType", "Workspace"):
        return
    changed = False
    for name in INDEPENDENT_WORKSPACES:
        if not frappe.db.exists("Workspace", name):
            continue
        if frappe.db.get_value("Workspace", name, "parent_page"):
            frappe.db.set_value(
                "Workspace", name, "parent_page", "",
                update_modified=False,
            )
            changed = True
    if frappe.db.exists("Workspace", "Marina Custom Apps"):
        if not frappe.db.get_value("Workspace", "Marina Custom Apps", "is_hidden"):
            frappe.db.set_value(
                "Workspace", "Marina Custom Apps", "is_hidden", 1,
                update_modified=False,
            )
            changed = True
    if changed:
        frappe.clear_cache(doctype="Workspace")
