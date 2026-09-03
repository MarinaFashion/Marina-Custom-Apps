frappe.query_reports["Forecast Accuracy Analysis"] = {
    filters: [
        {
            fieldname: "forecast_run",
            label: __("Forecast Run"),
            fieldtype: "Link",
            options: "Sales Forecast Run"
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date"
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date"
        },
        {
            fieldname: "branch",
            label: __("Branch"),
            fieldtype: "Link",
            options: "Branch"
        },
        {
            fieldname: "main_group",
            label: __("Main Group"),
            fieldtype: "Select",
            options: "\nDresses\nUppers\nBottoms"
        }
    ]
};
