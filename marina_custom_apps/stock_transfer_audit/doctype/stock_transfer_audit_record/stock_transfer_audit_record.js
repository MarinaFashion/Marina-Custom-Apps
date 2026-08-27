frappe.ui.form.on("Stock Transfer Audit Record", {
    setup(frm) {
        frm.set_query("original_send_stock", () => ({filters: {docstatus: 1, stock_entry_type: "Send Stock"}}));
        frm.set_query("receive_stock", () => ({filters: {docstatus: 1, stock_entry_type: "Receive Stock", outgoing_stock_entry: frm.doc.original_send_stock || ""}}));
    },
    refresh(frm) {
        if (!frm.is_new() && frm.doc.record_type === "Audit Run" && frm.doc.audit_status === "Open" && frm.doc.audit_result === "Variance") {
            frm.add_custom_button(__("Generate Correction Stock Entries"), async () => {
                if (frm.is_dirty()) await frm.save();
                const response = await frm.call("generate_correction_stock_entries");
                const result = response.message || {};
                frappe.msgprint({title: __("Audit Correction"), message: result.message || __("Done"), indicator: "green"});
                await frm.reload_doc();
            }, __("Actions"));
        }
    },
    original_send_stock(frm) { if (!frm.doc.original_send_stock) frm.set_value("receive_stock", null); },
});
