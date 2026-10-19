frappe.ui.form.on("Bank Statement Reconciliation Match", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.docstatus === 2) return;
        // This permission is only a visibility convenience; the server checks again.
        if (!frappe.model.can_write("Bank Statement Reconciliation") ||
            !frappe.model.can_read("Bank Statement Reconciliation Match")) return;
        frm.add_custom_button(__("Reverse Reconciliation"), () => {
            frappe.prompt(
                [{
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("Reason for Reversal"),
                    reqd: 1,
                    description: __("Required for the audit trail."),
                }],
                values => {
                    frappe.confirm(
                        __("Reverse this entire match and release all linked Bank and GL transactions for reconciliation again?"),
                        () => {
                            frappe.call({
                                method: "marina_custom_apps.pos_reconciliation.bank_match_reversal.reverse_match",
                                args: {match_name: frm.doc.name, reason: values.reason},
                                freeze: true,
                                freeze_message: __("Reversing reconciliation..."),
                                callback(r) {
                                    if (!r.message) return;
                                    frappe.show_alert({
                                        message: __("Reconciliation reversed. Bank and GL rows are available again."),
                                        indicator: "green",
                                    }, 5);
                                    frappe.set_route("List", "Bank Statement Reconciliation Match");
                                },
                            });
                        }
                    );
                },
                __("Reverse Reconciliation"),
                __("Reverse")
            );
        }).addClass("btn-danger");
    },
});
