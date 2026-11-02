app_name = "marina_design_management"
app_title = "Marina Design Management"
app_publisher = "Marina Fashion"
app_description = "Fashion design, document evidence, milestone steps and team custody"
app_email = ""
app_license = "Proprietary"
required_apps = ["erpnext"]

# Small desk-only client script; applies exclusively to Marina DocTypes.
app_include_js = ["/assets/marina_custom_apps/js/marina_usernames.js",
                  "/assets/marina_custom_apps/js/marina_discussions.js"]

after_install = "marina_custom_apps.design_management.setup.install.after_install"
after_migrate = "marina_custom_apps.design_management.setup.install.after_migrate"

# Daily cleanup is restricted to message-owned large chat attachments that
# explicitly carry an expiry date. bench migrate activates changed hooks.
scheduler_events = {
    "daily": ["marina_custom_apps.design_management.discussion_retention.expire_large_attachments"]
}

permission_query_conditions = {
    "Mood Board": "marina_custom_apps.design_management.security.permissions.mood_board_query",
    "Design Code": "marina_custom_apps.design_management.security.permissions.design_code_query",
    "Design Document": "marina_custom_apps.design_management.security.permissions.document_query",
    "Design Cost Breakdown": "marina_custom_apps.design_management.security.permissions.cost_breakdown_query",
    "Production Colorway": "marina_custom_apps.design_management.security.permissions.colorway_query",
}
has_permission = {
    "Mood Board": "marina_custom_apps.design_management.security.permissions.mood_board_permission",
    "Design Code": "marina_custom_apps.design_management.security.permissions.design_code_permission",
    "Design Document": "marina_custom_apps.design_management.security.permissions.document_permission",
    "Design Cost Breakdown": "marina_custom_apps.design_management.security.permissions.cost_breakdown_permission",
    "Production Colorway": "marina_custom_apps.design_management.security.permissions.colorway_permission",
}


# Additional reference/audit DocTypes use restrictive hooks. They never grant
# permissions beyond the native Frappe role permissions.
for _doctype, _fn in {
    "Design Milestone Type": "design_milestone_type",
    "Marina Fashion Category": "marina_fashion_category",
    "Marina Pantone": "marina_pantone",
    "Design Document Type": "design_document_type",
    "Design Management Settings": "design_management_settings",
    "Design Item Creation": "design_item_creation",
    "Design Cleanup Log": "design_cleanup_log",
    "Design Module Role": "design_module_role"
}.items():
    permission_query_conditions[_doctype] = (
        "marina_custom_apps.design_management.security.permissions." + _fn + "_query"
    )
    has_permission[_doctype] = (
        "marina_custom_apps.design_management.security.permissions.module_reference_permission"
    )
del _doctype, _fn

# Keep the read-only Link selector in sync when ERPNext Item Attribute > Size changes.
doc_events = {
    "Item Attribute": {
        "on_update": "marina_custom_apps.design_management.setup.size_reference.sync_when_size_changed",
    },
}


# Discussion records are read only through parent-scoped APIs. File ownership
# is Administrator so uploaders cannot retain access after team reassignment.
has_permission["Marina Discussion Message"] = "marina_custom_apps.design_management.discussions.has_permission"
permission_query_conditions["Marina Discussion Message"] = "marina_custom_apps.design_management.discussions.query_condition"
permission_query_conditions["File"] = "marina_custom_apps.design_management.discussions.file_query_condition"

for _discussion_parent in ("Design Code", "Mood Board"):
    doc_events.setdefault(_discussion_parent, {})["on_trash"] = "marina_custom_apps.design_management.discussions.archive_on_parent_delete"
del _discussion_parent

has_permission["File"] = "marina_custom_apps.design_management.discussions.file_permission"
