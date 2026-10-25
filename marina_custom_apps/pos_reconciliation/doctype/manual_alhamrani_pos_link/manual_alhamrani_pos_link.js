frappe.ui.form.on("Manual Alhamrani POS Link", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status !== "Approved") return;
        if (!frappe.user_roles.includes("Accounts Manager") &&
            !frappe.user_roles.includes("System Manager")) return;

        // Retry only remaining empty fields without replacing previous source
        // values or their original enrichment/rollback audit.
        const existing = !!frm.doc.enrichment_details;
        const label = existing ? __("Enrich Remaining Fields") : __("Enrich Missing Fields");
        frm.add_custom_button(label, () => {
            frappe.confirm(
                __("Fill any eligible empty Alhamrani fields from the approved Bank POS transaction? Original response and existing values remain unchanged."),
                () => frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service.enrich_existing_manual_link",
                    args: {link_name: frm.doc.name},
                    freeze: true,
                    freeze_message: __("Checking remaining bank-verified fields...")
                }).then(result => {
                    if (!result.message) return;
                    const data = result.message.enrichment || {};
                    const added = data.fields || [];
                    const skipped = data.skipped || [];
                    const fieldNames = {
                        masked_card_number: __("Masked Card Number"),
                        card_type: __("Card Type"),
                        terminal_id: __("Terminal ID"),
                        auth_code: __("Auth Code")
                    };
                    const details = skipped.map(row =>
                        "<li>" + frappe.utils.escape_html(fieldNames[row.field] || row.field || "") +
                        ": " + frappe.utils.escape_html(row.reason || "") + "</li>"
                    ).join("");
                    frappe.msgprint({
                        title: __("Bank Data Enrichment"),
                        message: "<p>" + __("Status: {0}. Newly populated fields: {1}.", [
                            frappe.utils.escape_html(data.status || "—"),
                            added.length
                        ]) + "</p>" +
                        (details ? "<p>" + __("Fields not updated:") + "</p><ul>" + details + "</ul>" : ""),
                        indicator: added.length ? "green" : "orange"
                    });
                    frm.reload_doc();
                })
            );
        }, __("Actions"));

        frm.add_custom_button(__("Unlink Transactions"), () => {
            const dialog = new frappe.ui.Dialog({
                title: __("Unlink Alhamrani and Bank POS Transactions"),
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "unlink_warning",
                        options: "<p>" + __(
                            "This will revoke the approved manual link, retain the unlink history, " +
                            "and restore only fields previously copied from the Bank POS transaction."
                        ) + "</p><p><b>" + __(
                            "Bank settlements and statement reconciliations will not be deleted. " +
                            "You must rerun POS Reconciliation before creating a new manual link."
                        ) + "</b></p>"
                    },
                    {
                        fieldtype: "Small Text",
                        fieldname: "unlink_reason",
                        label: __("Reason for Unlinking"),
                        reqd: 1,
                        description: __("At least 10 characters. This reason becomes part of the permanent audit history.")
                    }
                ],
                primary_action_label: __("Review Unlink"),
                primary_action(values) {
                    const reason = (values.unlink_reason || "").trim();
                    if (reason.length < 10 || reason.length > 2000) {
                        frappe.msgprint(__("Enter a reason between 10 and 2000 characters."));
                        return;
                    }
                    frappe.confirm(
                        __("Confirm unlink of Alhamrani {0} and Bank POS {1}? " +
                           "This action will retain the audit history and require a reconciliation rerun.", [
                            frappe.utils.escape_html(frm.doc.alhamrani_transaction || ""),
                            frappe.utils.escape_html(frm.doc.bank_pos_transaction || "")
                        ]),
                        () => {
                            frappe.call({
                                method: "marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service.unlink_manual_link",
                                args: {
                                    link_name: frm.doc.name,
                                    reason: reason
                                },
                                freeze: true,
                                freeze_message: __("Validating accounting and settlement references...")
                            }).then(result => {
                                if (!result.message || result.message.status !== "Revoked") return;
                                dialog.hide();
                                frappe.msgprint({
                                    title: __("Transactions Unlinked"),
                                    message: __("Manual link revoked; its original pairing and reason were retained. " +
                                        "No bank settlement or statement was deleted. Rerun POS Reconciliation " +
                                        "for the relevant date, POS Profile and Bank Account before relinking."),
                                    indicator: "green"
                                });
                                frm.reload_doc();
                            });
                        }
                    );
                }
            });
            dialog.show();
        }, __("Actions"));
    }
});
