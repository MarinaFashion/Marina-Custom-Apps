frappe.query_reports["POS Card Type Summary by Store"] = {
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
            fieldname: "pos_profile",
            label: __("POS Profile"),
            fieldtype: "Link",
            options: "POS Profile",
        },
        {
            fieldname: "card_type",
            label: __("Card Type"),
            fieldtype: "Select",
            options: "\nMada\nVisa\nMastercard\nGCC Card\nAmerican Express",
        },
    ],
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (data && data.is_group) {
            value = `<strong>${value}</strong>`;
        }
        return value;
    },
};
