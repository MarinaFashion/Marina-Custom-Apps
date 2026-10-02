function selected_bank_transactions(listview) {
    return listview.get_checked_items().map((row) => row.name);
}

frappe.listview_settings["Bank POS Transaction"] = {
    onload(listview) {
        listview.page.add_inner_button(__("Refresh POS Profile Locations"), () => {
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.doctype.bank_pos_transaction.bank_pos_transaction.refresh_all_bank_transaction_locations",
                freeze: true,
                freeze_message: __("Refreshing POS Profile locations..."),
            }).then((r) => {
                const result = r.message || {};
                frappe.msgprint({
                    title: __("POS Profile Locations Refreshed"),
                    indicator: result.unresolved ? "orange" : "green",
                    message: __(
                        "{0} transactions checked, {1} updated, {2} resolved, {3} unresolved.",
                        [
                            result.total || 0,
                            result.updated || 0,
                            result.resolved || 0,
                            result.unresolved || 0,
                        ]
                    ),
                });
                listview.refresh();
            });
        });

        listview.page.add_actions_menu_item(__("Mark Reconciliation Cleared"), () => {
            const names = selected_bank_transactions(listview);
            if (!names.length) {
                frappe.msgprint(__("Select at least one bank transaction."));
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
                        method: "marina_custom_apps.pos_reconciliation.manual_clearance.mark_selected_bank_transactions",
                        args: { bank_transactions: names, reason: values.reason },
                        freeze: true,
                        freeze_message: __("Saving manual reconciliation clearance..."),
                    }).then(() => listview.refresh());
                },
                __("Manual Reconciliation Clearance"),
                __("Clear")
            );
        });

        listview.page.add_actions_menu_item(__("Reopen Reconciliation Clearance"), () => {
            const names = selected_bank_transactions(listview);
            if (!names.length) {
                frappe.msgprint(__("Select at least one bank transaction."));
                return;
            }
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.manual_clearance.reopen_selected_bank_transactions",
                args: { bank_transactions: names },
                freeze: true,
                freeze_message: __("Reopening manual reconciliation clearance..."),
            }).then(() => listview.refresh());
        });
    },
};
