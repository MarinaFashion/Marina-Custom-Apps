frappe.query_reports["PO Receipt Variance Discount"] = {
    onload(report) {
        report.page.add_inner_button(__("Excel Matrix Layout"), () => {
            frappe.route_options = report.get_filter_values();
            frappe.set_route("po-receipt-variance-matrix");
        });
    },
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
            options: "Item Template\nItem Variant", default: "Item Variant", reqd: 1,
            description: __("Discount eligibility always calculated per Item Variant; template view only sums the variant results."),
        },
        {fieldname: "item_year", label: __("Year"), fieldtype: "Data"},
        {fieldname: "season", label: __("Season"), fieldtype: "Data"},
        {fieldname: "collection", label: __("Collection"), fieldtype: "Data"},
        {
            fieldname: "report_currency", label: __("Currency"), fieldtype: "Select",
            options: "CNY\nSAR", default: "CNY", reqd: 1,
            description: __("CNY from original PO transaction rates; SAR from original PO base rates."),
        },
        {
            fieldname: "tolerance_pct", label: __("Tolerance %"), fieldtype: "Percent",
            default: 8, reqd: 1,
            description: __("Allowance is rounded independently for each Item Variant."),
        },
        {
            fieldname: "discount_pct", label: __("Excess Discount %"), fieldtype: "Percent",
            default: 50, reqd: 1, description: __("Discount applied only to the eligible excess quantity."),
        },
    ],
};
