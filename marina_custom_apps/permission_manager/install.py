import frappe


MODULE_NAME = "Permission Manager"
WORKSPACE_NAME = "Permission Manager Dashboard"
APP_NAME = "marina_custom_apps"
PARENT_WORKSPACE = "Marina Custom Apps"


def after_install():
    _claim_module_ownership()
    _repair_workspace_hierarchy()


def after_migrate():
    _claim_module_ownership()
    _repair_workspace_hierarchy()


def _claim_module_ownership():
    """Move the existing standalone module under Marina Custom Apps.

    The standalone app and the merged module intentionally use the same Frappe
    Module Def, Page, Report, Number Card, and Workspace names. Reusing those
    records preserves routes and all permissions already configured through
    the manager while the Python/API namespace moves into this app.
    """
    if not frappe.db.exists("DocType", "Module Def"):
        return

    values = {
        "module_name": MODULE_NAME,
        "app_name": APP_NAME,
        "custom": 0,
    }
    if frappe.db.exists("Module Def", MODULE_NAME):
        frappe.db.set_value(
            "Module Def",
            MODULE_NAME,
            values,
            update_modified=False,
        )
    else:
        frappe.get_doc(
            {
                "doctype": "Module Def",
                **values,
            }
        ).insert(ignore_permissions=True)

    frappe.clear_cache(doctype="Module Def")


def _repair_workspace_hierarchy():
    if not frappe.db.exists("DocType", "Workspace"):
        return
    if not frappe.db.exists("Workspace", WORKSPACE_NAME):
        return

    frappe.db.set_value(
        "Workspace",
        WORKSPACE_NAME,
        {
            "module": MODULE_NAME,
            "parent_page": PARENT_WORKSPACE,
            "sequence_id": 9.0,
            "public": 1,
            "is_hidden": 0,
        },
        update_modified=False,
    )
    frappe.clear_cache(doctype="Workspace")
