frappe.ui.form.on("Stock Transfer Audit Record", {
    setup(frm) {
        frm.set_query("original_send_stock", () => ({filters:{docstatus:1,stock_entry_type:"Send Stock"}}));
        frm.set_query("receive_stock", () => ({filters:{docstatus:1,stock_entry_type:"Receive Stock",outgoing_stock_entry:frm.doc.original_send_stock||""}}));
    },
    original_send_stock(frm) { if (!frm.doc.original_send_stock) frm.set_value("receive_stock", null); },
});
