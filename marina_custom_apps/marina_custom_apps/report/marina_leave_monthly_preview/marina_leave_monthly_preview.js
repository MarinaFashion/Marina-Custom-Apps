frappe.query_reports["Marina Leave Monthly Preview"] = {
    filters: [
        {fieldname: "credit_date", label: __("Credit Date (1st of Month)"),
         fieldtype: "Date", reqd: 1,
         default: frappe.datetime.get_today().slice(0, 8) + '01'},
        {fieldname: "employee", label: __("Employee"),
         fieldtype: "Link", options: "Employee"},
        {fieldname: "entitlement", label: __("Contract Entitlement"),
         fieldtype: "Select", options: "\nAnnual 21\nAnnual 30"},
        {fieldname: "include_exempt", label: __("Show Exempt Employees"),
         fieldtype: "Check", default: 0}
    ]
};
