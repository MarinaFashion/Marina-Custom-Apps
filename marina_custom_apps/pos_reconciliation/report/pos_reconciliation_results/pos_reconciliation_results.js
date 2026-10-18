frappe.query_reports["POS Reconciliation Results"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
        },
        {
            fieldname: "match_status",
            label: __("Match Status"),
            fieldtype: "Select",
            options: "\nFully Matching\nMatching Not Settled\nBank Only - Settled\nBank Only - Not Settled\nAlhamrani Only\nDiscrepancy",
        },
        {
            fieldname: "resolution_status",
            label: __("Resolution Status"),
            fieldtype: "Select",
            options: "\nAuto Cleared\nPending",
        },
        {
            fieldname: "settlement_number",
            label: __("Settlement Number"),
            fieldtype: "Data",
        },
        {
            fieldname: "settlement_date",
            label: __("Settlement Date"),
            fieldtype: "Date",
        },
        {
            fieldname: "terminal_id",
            label: __("Terminal ID"),
            fieldtype: "Data",
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
            fieldtype: "Data",
        },
        {
            fieldname: "before_integration",
            label: __("Before Integration Only"),
            fieldtype: "Check",
            default: 0,
        },
    ],
};
