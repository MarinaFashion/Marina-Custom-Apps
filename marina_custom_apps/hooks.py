app_name = "marina_custom_apps"
app_title = "Marina Custom Apps"
app_publisher = "Marina Trading Company"
app_description = "Marina Trading Company custom Frappe/ERPNext modules"
app_email = "it@marinafashion.com.sa"
app_license = "MIT"
app_version = "0.53.8"

required_apps = ["erpnext"]

calendars = ["Marina Calendar Event"]

after_install = "marina_custom_apps.sales_forecasting.install.app_after_install"
after_migrate = "marina_custom_apps.sales_forecasting.install.app_after_migrate"

doc_events = {
    "Journal Entry": {
        "before_submit": "marina_custom_apps.pos_reconciliation.journal_entry_line_references.before_submit",
        "before_cancel": "marina_custom_apps.pos_reconciliation.accounting_service.validate_generated_journal_entry_before_cancel",
        "on_submit": "marina_custom_apps.pos_reconciliation.accounting_service.on_journal_entry_submit",
        "on_cancel": "marina_custom_apps.pos_reconciliation.journal_entry_reconciliation_cleanup.on_cancel",
        "on_trash": "marina_custom_apps.pos_reconciliation.journal_entry_reconciliation_cleanup.on_trash",
    },
    "Stock Reconciliation": {
        "on_submit": "marina_custom_apps.cycle_count.stock_reconciliation_events.on_submit",
        "on_cancel": "marina_custom_apps.cycle_count.stock_reconciliation_events.on_cancel",
    },
    "Stock Entry": {
        "before_validate": "marina_custom_apps.stock_transfer_control.stock_entry_events.before_validate_stock_entry",
        "validate": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_stock_entry",
        "before_submit": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_submit",
        "before_cancel": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_cancel",
        "on_submit": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_submit",
        "on_cancel": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_cancel",
        "on_trash": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_trash",
    },
    "DC Dispatch Run": {
        "validate": "marina_custom_apps.dc_dispatch.services.planning_guard_service.validate_run",
    },
    "Material Request": {
        "on_cancel": "marina_custom_apps.dc_dispatch.material_request_events.clear_proposal_links",
        "on_trash": "marina_custom_apps.material_request_events.on_trash",
    },
}

doctype_js = {
    "Journal Entry": "public/js/bilingual_account_search.js",
    "Stock Entry": "public/js/stock_entry_control.js",
    "DC Dispatch Run": "public/js/dc_dispatch_run_v063.js",
    "Material Request": "public/js/material_request_logistics.js",
    "Purchase Receipt": "public/js/purchase_order_picker.js",
    "Purchase Invoice": "public/js/purchase_order_picker.js",
}


override_doctype_class = {
    "Stock Allocation Run": (
        "marina_custom_apps.stock_auto_allocation."
        "logistics_stock_allocation_run.LogisticsStockAllocationRun"
    ),
}

override_doctype_dashboards = {
    "Stock Entry": "marina_custom_apps.stock_transfer_audit.stock_entry_dashboard.get_data",
}

scheduler_events = {
    "daily": [
        "marina_custom_apps.stock_transfer_audit.alerts.send_daily_stock_transfer_control_alerts",
    ],
}

permission_query_conditions = {
    "Store Cycle Count": "marina_custom_apps.cycle_count.permissions.store_cycle_count_query",
    "SOP Document": "marina_custom_apps.sop_management.permissions.sop_document_query",
    "SOP Version": "marina_custom_apps.sop_management.permissions.sop_version_query",
}

has_permission = {
    "Store Cycle Count": "marina_custom_apps.cycle_count.permissions.store_cycle_count_permission",
    "SOP Document": "marina_custom_apps.sop_management.permissions.sop_document_permission",
    "SOP Version": "marina_custom_apps.sop_management.permissions.sop_version_permission",
}

# DESIGN MANAGEMENT INTEGRATION (independent Frappe business module)
# App shell stays marina_custom_apps; DocType/Workspace module is
# "Marina Design Management" and retains its business role permissions.
app_include_js = list(globals().get("app_include_js", [])) + [
    "/assets/marina_custom_apps/js/marina_usernames.js",
    "/assets/marina_custom_apps/js/marina_discussions.js",
    "/assets/marina_custom_apps/js/bulk_shipment_receiving_v2.js",
]
scheduler_events.setdefault("daily", []).append(
    "marina_custom_apps.design_management.discussion_retention.expire_large_attachments"
)

permission_query_conditions.update({
    "Mood Board": "marina_custom_apps.design_management.security.permissions.mood_board_query",
    "Design Code": "marina_custom_apps.design_management.security.permissions.design_code_query",
    "Design Document": "marina_custom_apps.design_management.security.permissions.document_query",
    "Design Cost Breakdown": "marina_custom_apps.design_management.security.permissions.cost_breakdown_query",
    "Production Colorway": "marina_custom_apps.design_management.security.permissions.colorway_query",
    "Marina Discussion Message": "marina_custom_apps.design_management.discussions.query_condition",
    "File": "marina_custom_apps.design_management.discussions.file_query_condition",
})
has_permission.update({
    "Mood Board": "marina_custom_apps.design_management.security.permissions.mood_board_permission",
    "Design Code": "marina_custom_apps.design_management.security.permissions.design_code_permission",
    "Design Document": "marina_custom_apps.design_management.security.permissions.document_permission",
    "Design Cost Breakdown": "marina_custom_apps.design_management.security.permissions.cost_breakdown_permission",
    "Production Colorway": "marina_custom_apps.design_management.security.permissions.colorway_permission",
    "Marina Discussion Message": "marina_custom_apps.design_management.discussions.has_permission",
    "File": "marina_custom_apps.design_management.discussions.file_permission",
})
for _mdm_dt, _mdm_code in {
    "Design Milestone Type": "design_milestone_type",
    "Marina Fashion Category": "marina_fashion_category",
    "Marina Pantone": "marina_pantone",
    "Design Document Type": "design_document_type",
    "Design Management Settings": "design_management_settings",
    "Design Item Creation": "design_item_creation",
    "Design Cleanup Log": "design_cleanup_log",
    "Design Module Role": "design_module_role",
}.items():
    permission_query_conditions[_mdm_dt] = (
        "marina_custom_apps.design_management.security.permissions." + _mdm_code + "_query"
    )
    has_permission[_mdm_dt] = (
        "marina_custom_apps.design_management.security.permissions.module_reference_permission"
    )
del _mdm_dt, _mdm_code

doc_events.setdefault("Item Attribute", {})["on_update"] = (
    "marina_custom_apps.design_management.setup.size_reference.sync_when_size_changed"
)
for _mdm_parent in ("Design Code", "Mood Board"):
    doc_events.setdefault(_mdm_parent, {})["on_trash"] = (
        "marina_custom_apps.design_management.discussions.archive_on_parent_delete"
    )
del _mdm_parent

# On an already-installed app, migration does not run bench install-app's
# add_module_defs(). Create the module identity BEFORE schema sync.
before_migrate = "marina_custom_apps.design_management.setup.module_ownership.ensure_design_module"

# Marina Design Management workspace navigation (Frappe v15).
# Both wrappers delegate to the original Frappe implementation and affect
# only the Marina Design Management workspace, not other app workspaces.
override_whitelisted_methods = dict(globals().get("override_whitelisted_methods", {}))
override_whitelisted_methods.update({
    "frappe.desk.desktop.get_workspace_sidebar_items":
        "marina_custom_apps.design_management.workspace_visibility.get_workspace_sidebar_items",
    "frappe.desk.desktop.get_desktop_page":
        "marina_custom_apps.design_management.workspace_visibility.get_desktop_page",
})
