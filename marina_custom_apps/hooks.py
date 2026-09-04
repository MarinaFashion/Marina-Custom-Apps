app_name = "marina_custom_apps"
app_title = "Marina Custom Apps"
app_publisher = "Marina Trading Company"
app_description = "Marina Trading Company custom Frappe/ERPNext modules"
app_email = "it@marinafashion.com.sa"
app_license = "MIT"
app_version = "0.43.4"

required_apps = ["erpnext"]

calendars = ["Marina Calendar Event"]

after_install = "marina_custom_apps.sales_forecasting.install.app_after_install"
after_migrate = "marina_custom_apps.sales_forecasting.install.app_after_migrate"

doc_events = {
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
    "Stock Entry": "public/js/stock_entry_control.js",
    "DC Dispatch Run": "public/js/dc_dispatch_run_v063.js",
    "Material Request": "public/js/material_request_logistics.js",
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
}

has_permission = {
    "Store Cycle Count": "marina_custom_apps.cycle_count.permissions.store_cycle_count_permission",
}
