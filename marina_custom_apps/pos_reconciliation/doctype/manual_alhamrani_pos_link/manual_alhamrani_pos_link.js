frappe.ui.form.on("Manual Alhamrani POS Link", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.status !== "Approved") return;
        if (!frappe.user_roles.includes("Accounts Manager") &&
            !frappe.user_roles.includes("System Manager")) return;

        // Links approved before bank enrichment was introduced are still
        // eligible for a one-time, separately confirmed Demo backfill.
        if (!frm.doc.enrichment_details &&
            !["Applied", "No Eligible Fields"].includes(frm.doc.enrichment_status)) {
            frm.add_custom_button(__("Enrich Missing Fields"), () => {
                frappe.confirm(
                    __("Copy available Bank POS evidence into empty Alhamrani fields? Original responses and financial postings will remain unchanged."),
                    () => frappe.call({
                        method: "marina_custom_apps.pos_reconciliation.manual_alhamrani_link_service.enrich_existing_manual_link",
                        args: {link_name: frm.doc.name},
                        freeze: true,
                        freeze_message: __("Checking and enriching approved payment link...")
                    }).then(result => {
                        if (!result.message) return;
                        const data = result.message.enrichment || {};
                        frappe.msgprint(__("Enrichment status: {0}. Fields populated: {1}.", [
                            data.status || "—",
                            (data.fields || []).length
                        ]));
                        frm.reload_doc();
                    })
                );
            }, __("Actions"));
        }
    }
});
