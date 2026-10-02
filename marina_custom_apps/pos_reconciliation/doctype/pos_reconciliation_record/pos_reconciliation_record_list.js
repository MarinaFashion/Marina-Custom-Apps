function selected_record_names(listview) {
    return listview.get_checked_items().map((row) => row.name);
}

frappe.listview_settings["POS Reconciliation Record"] = {
    add_fields: ["match_status", "resolution_status", "before_integration"],

    get_indicator(doc) {
        if (doc.resolution_status === "Manually Cleared") {
            return [__("Manually Cleared"), "blue", "resolution_status,=,Manually Cleared"];
        }
        if (doc.match_status === "Matching") {
            return [__("Matching"), "green", "match_status,=,Matching"];
        }
        if (doc.match_status === "Discrepancy") {
            return [__("Discrepancy"), "orange", "match_status,=,Discrepancy"];
        }
        if (doc.match_status === "Bank Only") {
            return [__("Bank Only"), "red", "match_status,=,Bank Only"];
        }
        return [__("Alhamrani Only"), "purple", "match_status,=,Alhamrani Only"];
    },

    onload(listview) {
        listview.page.add_actions_menu_item(__("Mark Bank Only as Manually Cleared"), () => {
            const names = selected_record_names(listview);
            if (!names.length) {
                frappe.msgprint(__("Select at least one reconciliation record."));
                return;
            }

            frappe.prompt(
                [{
                    fieldname: "reason",
                    label: __("Clearance Reason"),
                    fieldtype: "Small Text",
                    reqd: 1,
                    default: __("Pre-integration transaction"),
                }],
                (values) => {
                    frappe.call({
                        method: "marina_custom_apps.pos_reconciliation.manual_clearance.mark_selected_reconciliation_records",
                        args: { record_names: names, reason: values.reason },
                        freeze: true,
                        freeze_message: __("Clearing selected bank exceptions..."),
                    }).then(() => listview.refresh());
                },
                __("Manual Reconciliation Clearance"),
                __("Clear")
            );
        });

        listview.page.add_actions_menu_item(__("Reopen Manual Clearance"), () => {
            const names = selected_record_names(listview);
            if (!names.length) {
                frappe.msgprint(__("Select at least one reconciliation record."));
                return;
            }
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.manual_clearance.reopen_selected_reconciliation_records",
                args: { record_names: names },
                freeze: true,
                freeze_message: __("Reopening selected exceptions..."),
            }).then(() => listview.refresh());
        });
    },
};
