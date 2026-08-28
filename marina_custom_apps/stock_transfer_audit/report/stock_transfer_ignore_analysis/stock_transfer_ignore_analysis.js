frappe.query_reports["Stock Transfer Ignore Analysis"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1,
        },
        {
            fieldname: "target_warehouse",
            label: __("Target Warehouse"),
            fieldtype: "Link",
            options: "Warehouse",
        },
        {
            fieldname: "ignore_reason",
            label: __("Ignore Reason"),
            fieldtype: "Select",
            options: "\nReceiver Counting Error\nRecount Confirmed Correct\nData Entry Error\nAccepted Difference\nOther",
        },
    ],
};
