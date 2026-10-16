frappe.ui.form.on("Bank Reconciliation Exclusion", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status !== "Excluded") return;
        const manager = frappe.user.has_role("Accounts Manager") || frappe.user.has_role("System Manager");
        if (!manager) return;

        frm.add_custom_button(__("Restore Exclusion"), () => {
            frappe.prompt(
                [{
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("Restoration Reason"),
                    reqd: 1
                }],
                (values) => {
                    frappe.call({
                        method: "marina_custom_apps.pos_reconciliation.doctype.bank_statement_reconciliation.bank_statement_reconciliation.restore_exclusion",
                        args: { exclusion_name: frm.doc.name, reason: values.reason },
                        freeze: true
                    }).then(() => {
                        frappe.show_alert({ message: __("Transaction restored to reconciliation."), indicator: "green" });
                        frm.reload_doc();
                    });
                },
                __("Restore Transaction"),
                __("Restore")
            );
        }, __("Actions"));
    }
});
