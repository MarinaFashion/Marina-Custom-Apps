frappe.listview_settings["POS Bank Settlement"] = {
    add_fields: [
        "status",
        "settlement_number",
        "card_type",
        "gross_difference",
        "commission_difference",
        "vat_difference",
        "net_difference",
    ],
    get_indicator(doc) {
        const status = doc.status || "";
        const color = {
            "Fully Reconciled": "green",
            "Partial": "orange",
            "Amount Difference": "red",
            "ERP Settlement Only": "gray",
        }[status] || "gray";
        return [__(status || "Unknown"), color, `status,=,${status}`];
    },
};
