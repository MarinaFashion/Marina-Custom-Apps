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
    },
};
