frappe.query_reports["Marina Leave Monthly Preview"] = {
    filters: [
        {fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company"},
        {fieldname: "credit_date", label: __("Credit Date (Month End)"),
         fieldtype: "Date", reqd: 1,
         default: (() => {
             const now = frappe.datetime.get_today();
             const [year, month, day] = now.split("-").map(Number);
             const last = new Date(year, month, 0).getDate();
             return day === last
                 ? now
                 : frappe.datetime.add_days(now.slice(0, 8) + "01", -1);
         })()},
        {fieldname: "employee", label: __("Employee"),
         fieldtype: "Link", options: "Employee"},
        {fieldname: "entitlement", label: __("Contract Entitlement"),
         fieldtype: "Select", options: "\nAnnual 21\nAnnual 30"},
        {fieldname: "include_exempt", label: __("Show Exempt Employees"),
         fieldtype: "Check", default: 0}
    ]
};
