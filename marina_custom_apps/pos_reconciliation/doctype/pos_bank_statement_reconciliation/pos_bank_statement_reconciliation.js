frappe.ui.form.on("POS Bank Statement Reconciliation", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Build & Match"), () => {
            frappe.confirm(
                __("Build POS settlement groups from confirmed reconciliation results and match them to submitted ERPNext Bank Transactions for this bank account and date range?"),
                () => frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_statement_reconciliation.pos_bank_statement_reconciliation.run_statement_reconciliation",
                    args: { name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Reconciling bank statement...")
                }).then((r) => {
                    const x = r.message || {};
                    frappe.msgprint({
                        title: __("Bank Statement Reconciliation Completed"),
                        indicator: x.exception_settlements ? "orange" : "green",
                        message: __(
                            "Settlements: {0}<br>Fully Reconciled: {1}<br>Settlement Exceptions: {2}<br>Parsed POS Statement Lines: {3}<br>Unmatched POS Statement Lines: {4}<br>Other Bank Statement Lines: {5}",
                            [
                                x.settlement_count || 0,
                                x.fully_reconciled_settlements || 0,
                                x.exception_settlements || 0,
                                x.parsed_pos_statement_lines || 0,
                                x.unmatched_pos_statement_lines || 0,
                                x.other_statement_lines || 0
                            ]
                        )
                    });
                    frm.reload_doc();
                })
            );
        }).addClass("btn-primary");

        frm.add_custom_button(__("POS Bank Settlements"), () => {
            frappe.set_route("List", "POS Bank Settlement", {
                reconciliation_run: frm.doc.name
            });
        }, __("View"));

        frm.add_custom_button(__("Bank Transactions"), () => {
            frappe.set_route("List", "Bank Transaction", {
                bank_account: frm.doc.bank_account
            });
        }, __("View"));
    }
});
