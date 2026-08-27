app_name = "marina_custom_apps"
app_title = "Marina Custom Apps"
app_publisher = "Marina Trading Company"
app_description = "Marina Trading Company custom Frappe/ERPNext modules"
app_email = "it@marinafashion.com.sa"
app_license = "MIT"
app_version = "0.15.0"

required_apps = ["erpnext"]

after_install = "marina_custom_apps.install.after_install"
after_migrate = "marina_custom_apps.install.after_migrate"

doc_events = {
    "Stock Entry": {
        "before_validate": "marina_custom_apps.stock_transfer_control.stock_entry_events.before_validate_stock_entry",
        "validate": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_stock_entry",
        "before_submit": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_submit",
        "before_cancel": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_cancel",
        "on_submit": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_submit",
        "on_cancel": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_cancel",
        "on_trash": "marina_custom_apps.stock_transfer_audit.status_service.on_stock_entry_trash",
    },
}

doctype_js = {
    "Stock Entry": "public/js/stock_entry_control.js",
}
