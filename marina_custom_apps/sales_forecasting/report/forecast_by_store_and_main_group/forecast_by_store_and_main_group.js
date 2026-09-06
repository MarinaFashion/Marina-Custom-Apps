frappe.query_reports["Forecast by Store and Main Group"] = {
    tree: true,
    name_field: "name",
    parent_field: "parent",
    initial_depth: 0,
    filters: [
        { fieldname: "forecast_run", label: __("Forecast Run"), fieldtype: "Link", options: "Sales Forecast Run", reqd: 1 },
        { fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
        { fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
        { fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
        { fieldname: "show_units", label: __("Show Units"), fieldtype: "Check", default: 0 }
    ]
};