import frappe


def daily_refresh():
    try:
        from marina_custom_apps.sales_forecasting.services.data_mart import refresh_recent_data
        refresh_recent_data()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sales Forecast Daily Refresh Failed")
