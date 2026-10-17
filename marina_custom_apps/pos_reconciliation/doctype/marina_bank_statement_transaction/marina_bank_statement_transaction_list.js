function marina_demo_reset_escape(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function marina_demo_reset_count_table(summary) {
    const labels = [
        ["linked_bank_statement_transactions_to_delete", __("Linked Marina Bank Statement Transactions to DELETE")],
        ["bank_gl_reconciliation_matches_to_delete", __("Bank/GL match groups to DELETE")],
        ["gl_rows_released", __("GL entries to release (NOT delete)")],
        ["pos_settlements_to_reset", __("POS Bank Settlements to reset (NOT delete)")],
        ["pos_reconciliation_records_to_reset", __("POS Reconciliation Records to reset (NOT delete)")],
        ["imported_pos_transactions_preserved", __("Imported Bank POS Transactions preserved")],
        ["unlinked_bank_statement_transactions_preserved", __("Unlinked Bank Statement Transactions preserved")]
    ];
    return '<table class="table table-bordered table-sm">' +
        labels.map(([key, label]) =>
            "<tr><td>" + marina_demo_reset_escape(label) + "</td><td class='text-right'><b>" +
            cint(summary[key] || 0) + "</b></td></tr>").join("") + "</table>";
}

function marina_demo_reset_preview() {
    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.demo_bank_statement_reset.preview_demo_bank_statement_reset",
        freeze: true
    }).then((r) => {
        const data = r.message || {};
        const summary = data.summary || {};
        const blockers = data.blockers || [];
        const table = marina_demo_reset_count_table(summary);
        if (!data.can_proceed || blockers.length) {
            frappe.msgprint({
                title: __("Demo Bank Statement Reset Blocked"),
                indicator: "orange",
                message: table + "<p>" +
                    __("Reset has not been queued. Resolve these issues before proceeding:") +
                    "</p><ul>" + blockers.map(x =>
                        "<li>" + marina_demo_reset_escape(x) + "</li>").join("") + "</ul>"
            });
            return;
        }
        frappe.confirm(
            "<p><strong>" + __("DEMO ONLY — delete linked bank statement transaction test data?") +
            "</strong></p>" +
            "<p>" + __("This removes linked imported Bank Statement Transaction rows and Bank/GL matching records; it keeps imported Bank POS Transactions, GL Entries, unlinked statement rows and POS Reconciliation Records.") +
            "</p>" + table +
            "<p><strong>" + __("Take a full Demo database backup first. This action is not reversible without a backup.") + "</strong></p>",
            () => {
                frappe.prompt([
                    {
                        fieldname: "confirmation", fieldtype: "Data", reqd: 1,
                        label: __("Type DELETE DEMO LINKED BANK STATEMENTS")
                    }
                ], (values) => {
                    if (values.confirmation !== "DELETE DEMO LINKED BANK STATEMENTS") {
                        frappe.msgprint(__("Confirmation phrase does not match; no data changed."));
                        return;
                    }
                    frappe.call({
                        method: "marina_custom_apps.pos_reconciliation.demo_bank_statement_reset.queue_demo_bank_statement_reset",
                        args: {confirmation: values.confirmation, fingerprint: data.fingerprint},
                        freeze: true
                    }).then((queued) => {
                        frappe.msgprint({
                            title: __("Demo Bank Statement Reset Queued"),
                            indicator: "blue",
                            message: __("Wait for the long worker and use Check Demo Reset Status before running any new reconciliation.") +
                                " " + marina_demo_reset_escape((queued.message || {}).job_id || "")
                        });
                    });
                }, __("Confirm Demo Reset"), __("Queue Reset"));
            }
        );
    });
}

function marina_demo_reset_status() {
    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.demo_bank_statement_reset.get_demo_bank_statement_reset_status"
    }).then((r) => {
        const result = r.message || {};
        const status = result.status || "Not Started";
        const details = result.error
            ? "<pre style='white-space:pre-wrap;'>" + marina_demo_reset_escape(result.error) + "</pre>"
            : result.summary ? marina_demo_reset_count_table(result.summary) : "";
        frappe.msgprint({
            title: __("Demo Bank Statement Reset Status"),
            indicator: status === "Completed" ? "green" : status === "Failed" ? "red" : "blue",
            message: "<b>" + marina_demo_reset_escape(status) + "</b>" + details
        });
    });
}

frappe.listview_settings["Marina Bank Statement Transaction"] = {
    onload(listview) {
        if (!frappe.user.has_role("System Manager")) return;
        listview.page.add_inner_button(__("Preview Demo Linked Reset"), marina_demo_reset_preview);
        listview.page.add_inner_button(__("Check Demo Reset Status"), marina_demo_reset_status);
    },
    add_fields: ["reconciliation_status", "is_pos_statement_line", "component"],
    get_indicator(doc) {
        const status = doc.reconciliation_status || "Unreconciled";
        const color = {
            "Reconciled": "green",
            "Partially Reconciled": "orange",
            "Unreconciled": "red",
            "Excluded": "gray",
        }[status] || "gray";
        return [__(status), color, `reconciliation_status,=,${status}`];
    },
};
