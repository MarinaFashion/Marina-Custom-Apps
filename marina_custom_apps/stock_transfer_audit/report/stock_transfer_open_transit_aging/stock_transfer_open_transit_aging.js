frappe.query_reports["Stock Transfer Open Transit Aging"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "status",
            label: __("Status"),
            fieldtype: "Select",
            options: "\nOpen\nDue Soon\nOverdue\nCritical",
        },
        {
            fieldname: "source_warehouse",
            label: __("Source Warehouse"),
            fieldtype: "Link",
            options: "Warehouse",
        },
        {
            fieldname: "target_warehouse",
            label: __("Target Warehouse"),
            fieldtype: "Link",
            options: "Warehouse",
        },
    ],
};
