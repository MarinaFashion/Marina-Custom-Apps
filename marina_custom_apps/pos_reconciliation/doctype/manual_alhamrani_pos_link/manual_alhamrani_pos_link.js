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
            frappe.confirm(
                __("Unlink Alhamrani {0} from Bank POS {1}? " +
                   "The link will be deleted only after financial safety checks. " +
                   "Bank settlements and statement records are preserved. " +
                   "Rerun POS Reconciliation before relinking.", [
                    frappe.utils.escape_html(frm.doc.alhamrani_transaction || ""),
                    frappe.utils.escape_html(frm.doc.bank_pos_transaction || "")
                ]),
                () => frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service.unlink_manual_link",
                    args: {link_name: frm.doc.name},
                    freeze: true,
                    freeze_message: __("Checking accounting and settlement dependencies...")
                }).then(result => {
                    if (!result.message || !result.message.unlinked) return;
                    frappe.msgprint({
                        title: __("Manual Link Removed"),
                        message: __("Both payment sources are available for relinking after " +
                            "rerunning POS Reconciliation for the same period. " +
                            "No bank settlement, bank statement or accounting records were deleted."),
                        indicator: "green"
                    });
                    frappe.set_route("List", "Manual Alhamrani POS Link");
                })
            );
        }, __("Actions"));
    }
});
