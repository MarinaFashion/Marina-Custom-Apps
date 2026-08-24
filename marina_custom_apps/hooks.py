app_name = "marina_custom_apps"
app_title = "Marina Custom Apps"
app_publisher = "Marina Trading Company"
app_description = "Marina Trading Company custom Frappe/ERPNext modules"
app_email = "it@marinafashion.com.sa"
app_license = "MIT"
app_version = "0.2.0"

required_apps = ["erpnext"]

after_install = "marina_custom_apps.install.after_install"
after_migrate = "marina_custom_apps.install.after_migrate"

# v0.2.0 deliberately does not attach Stock Entry validation hooks yet.
# The backend policy foundation and custom fields are installed first.
# Transaction enforcement will be enabled only after the policy layer
# is reviewed against the existing Marina Stock Entry scripts.
