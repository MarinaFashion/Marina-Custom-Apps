"""Role and reference-data setup. Idempotent, no destructive data migration."""
import frappe

# The one standard Frappe role for ordinary Design Management users. Business
# roles, assigned/all scope, and workflow authorities live in Design Module Role.
PARTICIPANT_ROLE = "Marina Design Participant"
ROLES = [PARTICIPANT_ROLE]

# For one-time audit / removal of module-*managed* grants only. Pre-existing
# manually assigned standard roles are never deleted during migration.
PERMS = {
    "Marina Fashion Category": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Marina Pantone": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Mood Board": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 1, 1, 0),
    },
    "Design Code": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 1, 1, 1),
    },
    "Design Size Reference": {
        "System Manager": (1, 0, 0, 0), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Design Milestone Type": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Design Document": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 1, 1, 0),
    },
    "Design Cost Breakdown": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 1, 1, 0),
    },
    "Design Document Type": {
        "System Manager": (1, 1, 1, 1), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Design Management Settings": {
        "System Manager": (1, 1, 1, 1),
    },
    "Design Milestone Plan Entry": {
        "System Manager": (1, 0, 0, 0), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Design Milestone Execution": {
        "System Manager": (1, 0, 0, 0), PARTICIPANT_ROLE: (1, 0, 0, 0),
    },
    "Production Colorway": {PARTICIPANT_ROLE: (1, 1, 1, 0)},
    "Design Item Creation": {PARTICIPANT_ROLE: (1, 0, 0, 0)},
}

# Native Frappe permissions are just a ceiling. The application's own
# DocType/action/record checks are still required on every protected request.
# Never remove historic DocPerm or Role records here; other apps may use them.

def _bootstrap(*, migrate=False):
    sync_roles()
    sync_workspace_roles()
    sync_permissions()
    # Existing Single DocType rows may not have values for newly added fields.
    # Only initialize missing settings; never overwrite administrator choices.
    if frappe.db.exists("DocType", "Design Management Settings"):
        for fieldname, default in (
            ("discussion_retention_threshold_mb", 50),
            ("discussion_retention_days", 14),
        ):
            if frappe.db.get_single_value("Design Management Settings", fieldname) in (None, ""):
                frappe.db.set_single_value("Design Management Settings", fieldname, default)
    from marina_custom_apps.design_management.setup.module_role_defaults import sync_module_roles
    sync_module_roles()
    from marina_custom_apps.design_management.setup.module_role_defaults import sync_cost_breakdown_permissions
    sync_cost_breakdown_permissions()
    sync_document_types()
    # Bootstrap the new workflow on a clean install, never rewrite changed
    # milestone templates during bench migrate.
    from marina_custom_apps.design_management.clean_milestones.templates import seed_initial_master
    seed_initial_master()
    from marina_custom_apps.design_management.setup.size_reference import sync_size_references
    sync_size_references(migrate_existing=True)
    from marina_custom_apps.design_management.factory_options import migrate_factory_master
    migrate_factory_master()
    if migrate:
        from marina_custom_apps.design_management.setup.category_tree import migrate_category_tree
        migrate_category_tree()
        from marina_custom_apps.design_management.setup.pantone_metadata import repair_pantone_import_metadata
        repair_pantone_import_metadata()


def after_install():
    _bootstrap()


def after_migrate():
    _bootstrap(migrate=True)


def sync_roles():
    for role in ROLES:
        if not frappe.db.exists("Role",role):
            frappe.get_doc({"doctype":"Role","role_name":role,"desk_access":1}).insert(ignore_permissions=True)

def sync_permissions():
    from frappe.permissions import add_permission,update_permission_property
    for doctype,mapping in PERMS.items():
        if not frappe.db.exists("DocType",doctype):
            continue
        for role,flags in mapping.items():
            if not frappe.db.exists("DocPerm",{"parent":doctype,"role":role,"permlevel":0}):
                add_permission(doctype,role,0)
            for prop,value in zip(("read","write","create","delete"),flags):
                update_permission_property(doctype,role,0,prop,value)
            if doctype == "Design Code":
                update_permission_property(doctype, role, 0, "report", 1)

def sync_document_types():
    if not frappe.db.exists("DocType","Design Document Type"):
        return
    for name in ("Tech Pack", "Fitting Report", "QC Report", "Shipping Document", "Other"):
        if not frappe.db.exists("Design Document Type",name):
            frappe.get_doc({"doctype":"Design Document Type",
                            "document_type":name,"is_active":1}).insert(ignore_permissions=True)



def sync_workspace_roles():
    """Keep the app workspace on the two supported standard access roles."""
    name = "Marina Design Management"
    if not frappe.db.exists("Workspace", name):
        return
    workspace = frappe.get_doc("Workspace", name)
    roles = ["System Manager", PARTICIPANT_ROLE]
    if [row.role for row in workspace.roles] == roles:
        return
    workspace.set("roles", [{"role": role} for role in roles])
    workspace.save(ignore_permissions=True)
    frappe.clear_cache(doctype="Workspace")
