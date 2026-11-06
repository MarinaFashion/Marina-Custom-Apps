"""Register and resolve the Design module before DocType schema sync.

Frappe v15 resolves DocType Python controllers using frappe.local.module_app,
a reverse map cached as installed_app_modules. After the standalone Design app
has been consolidated, that cache can still point to the removed package.
A correct Module Def row alone does not refresh this mapping.
"""
import frappe

MODULE = "Marina Design Management"
OWNER = "marina_custom_apps"
LEGACY_APP = "marina_design_management"


def ensure_design_module():
    installed = set(frappe.get_installed_apps(_ensure_on_bench=True))
    if OWNER not in installed:
        frappe.throw("Marina Custom Apps must be installed to own the Design module")
    if LEGACY_APP in installed:
        frappe.throw(
            "The standalone marina_design_management app is still installed. "
            "Complete its controlled consolidation before migrating Marina Custom Apps."
        )

    old = frappe.db.get_value("Module Def", MODULE, "app_name")
    if old and old != OWNER:
        frappe.throw(
            "Module Def 'Marina Design Management' is still owned by "
            + str(old) + ". Correct its ownership during the controlled "
            "consolidation before migration."
        )
    if not old:
        frappe.get_doc({
            "doctype": "Module Def",
            "module_name": MODULE,
            "app_name": OWNER,
        }).insert(ignore_permissions=True)

    # Rebuild Frappe v15's *installed* app module map from modules.txt,
    # rather than trusting the old Redis mapping from the standalone app.
    # This runs before sync_all, including on a migration previously aborted
    # by a missing Design DocType controller import.
    frappe.cache.delete_value("installed_app_modules")
    frappe.setup_module_map(include_all_apps=False)
    key = frappe.scrub(MODULE)
    actual = frappe.local.module_app.get(key)
    if actual != OWNER:
        frappe.throw(
            "Design module import routing is incorrect: expected "
            + OWNER + ", got " + str(actual)
            + ". Check modules.txt and installed apps before migration."
        )
    frappe.clear_cache()
