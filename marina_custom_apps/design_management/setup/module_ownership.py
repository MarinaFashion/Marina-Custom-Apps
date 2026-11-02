"""Register the new design module *before* Frappe syncs standard DocTypes.

Frappe's install_app() creates Module Def rows, but migrations of an existing
app with a newly-added module do not automatically do that. This pre-migrate
hook is safe and idempotent; never delete or transfer documents here.
"""
import frappe

MODULE = "Marina Design Management"
OWNER = "marina_custom_apps"


def ensure_design_module():
    old = frappe.db.get_value("Module Def", MODULE, "app_name")
    if old:
        if old != OWNER:
            frappe.throw(
                "Module Def 'Marina Design Management' is still owned by "
                + str(old) + ". Uninstall the standalone design app from "
                "the demo site before deploying the consolidated app."
            )
        return
    frappe.get_doc({
        "doctype": "Module Def",
        "module_name": MODULE,
        "app_name": OWNER,
    }).insert(ignore_permissions=True)
    frappe.clear_cache()
