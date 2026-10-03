frappe.query_reports["POS Reconciliation Results"] = {
    filters: [
        {
            fieldname: "run",
            label: __("Reconciliation Run"),
            fieldtype: "Link",
            options: "POS Reconciliation Run",
            reqd: 1,
        },
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
            options: "\nMatching\nDiscrepancy\nBank Only\nAlhamrani Only",
        },
        {
            fieldname: "resolution_status",
            label: __("Resolution Status"),
            fieldtype: "Select",
            options: "\nAuto Cleared\nPending\nManually Cleared",
        },
        {
            fieldname: "finance_review_status",
            label: __("Finance Review"),
            fieldtype: "Select",
            options: "\nNot Required\nPending Review\nChecked & Approved\nNeeds Investigation",
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
