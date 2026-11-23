frappe.query_reports["Marina Leave Reconciliation"] = {
    filters: [
        {fieldname: "as_of", label: __("As Of"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1},
        {fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee"},
        {fieldname: "entitlement", label: __("Contract Entitlement"), fieldtype: "Select", options: "\nAnnual 21\nAnnual 30"},
        {fieldname: "include_exempt", label: __("Show Exempt Employees"), fieldtype: "Check", default: 1}
    ]
};
