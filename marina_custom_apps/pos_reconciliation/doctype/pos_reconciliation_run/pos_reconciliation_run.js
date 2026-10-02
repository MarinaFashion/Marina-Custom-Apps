frappe.ui.form.on("POS Reconciliation Run", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        if (frm.doc.status === "Draft") {
            frm.set_intro(
                __("Click Run Reconciliation to load and compare the approved Bank POS and Alhamrani transactions for this period."),
                "blue"
            );
        } else if (frm.doc.status === "Completed") {
            frm.set_intro(
                __("This run is completed. Use Re-run Reconciliation if source transactions have changed."),
                "green"
            );
        }

        const run_label = frm.doc.status === "Completed"
            ? __("Re-run Reconciliation")
            : __("Run Reconciliation");

        if (frm.doc.status !== "Running" && !frm.is_dirty()) {
            const run_button = frm.add_custom_button(run_label, () => {
                frappe.confirm(
                    __("Reconcile approved Bank POS transactions against approved Alhamrani transactions for this period?"),
                    () => {
                        frappe.call({
                            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.run_reconciliation",
                            args: { run_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __("Reconciling POS transactions..."),
                        }).then((r) => {
                            const result = r.message || {};
                            frm.reload_doc();
                            frappe.msgprint({
                                title: __("Reconciliation Completed"),
                                indicator: result.pending_count ? "orange" : "green",
                                message: __(
                                    "Matching: {0}<br>Discrepancies: {1}<br>Bank Only: {2}<br>Alhamrani Only: {3}<br>Manually Cleared: {4}<br>Pending: {5}",
                                    [
                                        result.matching_count || 0,
                                        result.discrepancy_count || 0,
                                        result.bank_only_count || 0,
                                        result.alhamrani_only_count || 0,
                                        result.manually_cleared_count || 0,
                                        result.pending_count || 0,
                                    ]
                                ),
                            });
                        });
                    }
                );
            });
            run_button.addClass("btn-primary");
        }


        frm.add_custom_button(__("All Records"), () => {
            frappe.set_route("List", "POS Reconciliation Record", { run: frm.doc.name });
        }, __("View"));

        frm.add_custom_button(__("Pending Exceptions"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Matching"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Matching",
            });
        }, __("View"));

        frm.add_custom_button(__("Discrepancies"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Discrepancy",
            });
        }, __("View"));

        frm.add_custom_button(__("Pending Bank Only"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Bank Only",
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Pending Alhamrani Only"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Alhamrani Only",
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Manually Cleared"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                resolution_status: "Manually Cleared",
            });
        }, __("View"));
    },
});
