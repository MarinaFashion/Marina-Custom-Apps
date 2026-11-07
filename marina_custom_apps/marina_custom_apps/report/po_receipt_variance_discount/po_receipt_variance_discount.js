frappe.query_reports["PO Receipt Variance Discount"] = {
    filters: [
        {
            fieldname: "company", label: __("Company"), fieldtype: "Link",
            options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "supplier", label: __("Supplier"), fieldtype: "Link",
            options: "Supplier", reqd: 1, default: "MIDMAK CNY",
        },
        {
            fieldname: "view_level", label: __("View Level"), fieldtype: "Select",
            options: "Item Template\nItem Variant", default: "Item Template", reqd: 1,
        },
        {fieldname: "item_year", label: __("Year"), fieldtype: "Data"},
        {fieldname: "season", label: __("Season"), fieldtype: "Data"},
        {fieldname: "collection", label: __("Collection"), fieldtype: "Data"},
        {
            fieldname: "tolerance_pct", label: __("Tolerance %"), fieldtype: "Percent",
            default: 5, reqd: 1, description: __("Only excess above this percentage qualifies for a discount."),
        },
        {
            fieldname: "discount_pct", label: __("Excess Discount %"), fieldtype: "Percent",
            default: 50, reqd: 1, description: __("Discount applied only to the eligible excess quantity."),
        },
    ],
};
