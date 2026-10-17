frappe.ui.form.on("POS Bank Statement Reconciliation", {
    refresh(frm) {
        frm.set_intro(
            __("Deprecated experimental document. Bank statement reconciliation now runs from the POS Reconciliation Control using Marina Bank Statement Transaction."),
            "orange"
        );

        frm.add_custom_button(__("Open POS Reconciliation Control"), () => {
            frappe.set_route("Form", "POS Reconciliation Run", "POS Reconciliation Run");
        });

        frm.add_custom_button(__("Bank Statement Imports"), () => {
            frappe.set_route("List", "Marina Bank Statement Import");
        }, __("View"));

        frm.add_custom_button(__("Bank Statement Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction");
        }, __("View"));
    }
});
