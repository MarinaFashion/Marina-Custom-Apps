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
