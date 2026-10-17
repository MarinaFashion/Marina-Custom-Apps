frappe.listview_settings["Marina Bank Statement Transaction"] = {
    add_fields: ["reconciliation_status", "is_pos_statement_line", "component"],
    get_indicator(doc) {
        const status = doc.reconciliation_status || "Unreconciled";
        const color = {
            "Reconciled": "green",
            "Partially Reconciled": "orange",
            "Unreconciled": "red",
            "Excluded": "gray",
        }[status] || "gray";
        return [__(status), color, `reconciliation_status,=,${status}`];
    },
};
