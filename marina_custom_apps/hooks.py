app_name = "marina_custom_apps"
app_title = "Marina Custom Apps"
app_publisher = "Marina Trading Company"
app_description = "Marina Trading Company custom Frappe/ERPNext modules"
app_email = "it@marinafashion.com.sa"
app_license = "MIT"
app_version = "0.11.0"

required_apps = ["erpnext"]

after_install = "marina_custom_apps.install.after_install"
after_migrate = "marina_custom_apps.install.after_migrate"

doc_events = {
    "Stock Entry": {
        "validate": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_stock_entry",
        "before_submit": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_submit",
        "before_cancel": "marina_custom_apps.stock_transfer_control.stock_entry_events.validate_before_cancel",
    },
}

doctype_js = {
    "Stock Entry": "public/js/stock_entry_control.js",
}
