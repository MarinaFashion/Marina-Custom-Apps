frappe.ui.form.on("Stock Transfer Audit Run", {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Load Transfers"), async () => {
                if (!frm.doc.from_date || !frm.doc.to_date) { frappe.msgprint(__("Set From Date and To Date first.")); return; }
                const result = await frm.call("load_transfers"); frm.refresh_fields(); const m = result.message || {};
                frappe.show_alert({message: __("{0} transfers loaded: {1} clean, {2} with variance.",[m.loaded_count||0,m.clean_count||0,m.variance_count||0]), indicator:(m.variance_count||0)?"orange":"green"});
            });
        }
    },
});
