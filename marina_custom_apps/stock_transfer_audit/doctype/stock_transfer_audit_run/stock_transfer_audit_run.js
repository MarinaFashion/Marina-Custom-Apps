frappe.ui.form.on("Stock Transfer Audit Run", {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Load Transfers"), async () => {
                if (!frm.doc.from_date || !frm.doc.to_date) { frappe.msgprint(__("Set From Date and To Date first.")); return; }
                const result = await frm.call("load_transfers"); frm.refresh_fields(); const m = result.message || {};
                frappe.msgprint({
                    title: __("Audit Transfers Loaded"),
                    message: __("{0} eligible transfers loaded: {1} clean and {2} with variance.<br>{3} legacy receipts before {4} were excluded.<br>{5} previously audited transfers were excluded.", [m.loaded_count||0,m.clean_count||0,m.variance_count||0,m.legacy_excluded_count||0,m.audit_process_start_date||"",m.previously_audited_count||0]),
                    indicator: (m.variance_count||0) ? "orange" : "green"
                });
            });
        }
    },
});
