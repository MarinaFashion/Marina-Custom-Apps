frappe.ui.form.on("POS Bank Statement Reconciliation", {
    refresh(frm) {
        frm.set_intro(
            __("Deprecated experimental document. Bank statement reconciliation now runs from POS Reconciliation Run using Marina Bank Statement Transaction."),
            "orange"
        );

        frm.add_custom_button(__("Open POS Reconciliation Runs"), () => {
            frappe.set_route("List", "POS Reconciliation Run");
        });

        frm.add_custom_button(__("Bank Statement Imports"), () => {
            frappe.set_route("List", "Marina Bank Statement Import");
        }, __("View"));

        frm.add_custom_button(__("Bank Statement Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction");
        }, __("View"));
    }
});
