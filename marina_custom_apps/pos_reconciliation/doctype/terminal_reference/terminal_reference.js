frappe.ui.form.on("Terminal Reference", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        frm.add_custom_button(__("Update Bank Transaction Locations"), () => {
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.doctype.terminal_reference.terminal_reference.refresh_bank_transaction_locations",
                args: { terminal_reference: frm.doc.name },
                freeze: true,
                freeze_message: __("Updating bank transaction locations..."),
            }).then((r) => {
                const result = r.message || {};
                frappe.msgprint({
                    title: __("Bank Transaction Locations Updated"),
                    indicator: result.unresolved ? "orange" : "green",
                    message: __(
                        "Terminal {0}: {1} transactions checked, {2} updated, {3} resolved, {4} unresolved.",
                        [
                            result.terminal_id || frm.doc.terminal_id,
                            result.total || 0,
                            result.updated || 0,
                            result.resolved || 0,
                            result.unresolved || 0,
                        ]
                    ),
                });
            });
        }, __("Actions"));
    },
});
