frappe.ui.form.on("POS Reconciliation Period Lock", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status !== "Closed") return;
        if (!(frappe.user.has_role("Accounts Manager") || frappe.user.has_role("System Manager"))) return;
        frm.add_custom_button(__("Reopen Period"), () => {
            frappe.prompt(
                [{fieldname:"reason",fieldtype:"Small Text",label:__("Reopen Reason"),reqd:1}],
                values => frappe.call({
                    method:"marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.reopen_reconciliation",
                    args:{run_name:"POS Reconciliation Run",period_lock:frm.doc.name,reason:values.reason},
                    freeze:true,
                }).then(() => frm.reload_doc()),
                __("Reopen Financial Period"), __("Reopen")
            );
        });
    },
});
