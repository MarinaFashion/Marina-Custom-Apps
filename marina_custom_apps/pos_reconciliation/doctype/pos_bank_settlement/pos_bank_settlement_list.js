
function pos_demo_cleanup_escape(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
}

function pos_demo_cleanup_summary(summary) {
    const fields = [
        ["settlements_to_delete", __("POS Bank Settlements to delete")],
        ["reconciliation_records_to_delete", __("Reconciliation Records to delete")],
        ["finance_clearances_to_delete", __("Manual Clearance decisions to delete")],
        ["statement_links_to_reset", __("Bank Statement links to reset")],
        ["imported_pos_transactions_preserved", __("Imported Bank POS Transactions preserved")],
        ["imported_statement_rows_preserved", __("Imported Bank Statement Transactions preserved")],
    ];
    return '<table class="table table-bordered table-sm">' +
        fields.map(([key, label]) => '<tr><td>' + label + '</td><td class="text-right"><b>' +
            cint(summary[key] || 0) + '</b></td></tr>').join("") +
        '</table>';
}

function pos_demo_cleanup_preview(listview) {
    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.demo_reconciliation_cleanup.preview_demo_reconciliation_cleanup",
        freeze: true,
    }).then((response) => {
        const data = response.message || {};
        const blockers = data.blockers || [];
        const table = pos_demo_cleanup_summary(data.summary || {});
        if (blockers.length || !data.can_proceed) {
            frappe.msgprint({
                title: __("Demo POS Cleanup Blocked"),
                indicator: "red",
                message: table + "<p>" + __("Cleanup was not started. Resolve the following safeguards first:") +
                    "</p><ul>" + blockers.map((item) =>
                        "<li>" + pos_demo_cleanup_escape(String(item)) + "</li>").join("") + "</ul>",
            });
            return;
        }
        frappe.confirm(
            '<p><b>' + __("DEMO ONLY: This permanently deletes derived POS reconciliation results and Finance manual decisions.") + '</b></p>' +
            '<p>' + __("Imported POS Bank Transactions and imported Bank Statement Transactions are preserved.") + '</p>' +
            table + '<p>' + __("A complete database backup is required before proceeding.") + '</p>',
            () => frappe.prompt(
                [{
                    fieldname: "confirmation",
                    fieldtype: "Data",
                    label: __("Type CLEAR DEMO POS RECONCILIATION"),
                    reqd: 1,
                    description: __("This action cannot be undone without restoring the Demo backup."),
                }],
                (values) => {
                    if (values.confirmation !== "CLEAR DEMO POS RECONCILIATION") {
                        frappe.msgprint(__("Confirmation phrase does not match; no cleanup queued."));
                        return;
                    }
                    frappe.call({
                        method: "marina_custom_apps.pos_reconciliation.demo_reconciliation_cleanup.queue_demo_reconciliation_cleanup",
                        args: {
                            confirmation: values.confirmation,
                            expected_signature: data.signature,
                        },
                        freeze: true,
                    }).then((queued) => {
                        const msg = queued.message || {};
                        frappe.msgprint({
                            title: __("Demo POS Cleanup Queued"),
                            indicator: "blue",
                            message: __("Cleanup is running on the long worker. Use Check Demo Cleanup Status before proceeding with migration.") +
                                " " + pos_demo_cleanup_escape(String(msg.job_id || "")),
                        });
                    });
                },
                __("Confirm Demo Cleanup"), __("Queue Cleanup")
            ),
        );
    });
}

function pos_demo_cleanup_status() {
    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.demo_reconciliation_cleanup.get_demo_reconciliation_cleanup_status",
    }).then((response) => {
        const data = response.message || {};
        const status = String(data.status || "Not Started");
        const error = data.error ? '<pre style="white-space:pre-wrap;">' +
            pos_demo_cleanup_escape(String(data.error)) + '</pre>' : "";
        frappe.msgprint({
            title: __("Demo POS Cleanup Status"),
            indicator: status === "Completed" ? "green" : status === "Failed" ? "red" : "blue",
            message: "<b>" + pos_demo_cleanup_escape(status) + "</b>" + error,
        });
    });
}

frappe.listview_settings["POS Bank Settlement"] = {
    onload(listview) {
        if (!frappe.user.has_role("System Manager")) return;
        listview.page.add_inner_button(__("Preview Demo POS Cleanup"), () => pos_demo_cleanup_preview(listview));
        listview.page.add_inner_button(__("Check Demo Cleanup Status"), pos_demo_cleanup_status);
    },
    add_fields: [
        "status",
        "settlement_number",
        "card_type",
        "gross_difference",
        "commission_difference",
        "vat_difference",
        "net_difference",
    ],
    get_indicator(doc) {
        const status = doc.status || "";
        const color = {
            "Fully Reconciled": "green",
            "Partial": "orange",
            "Amount Difference": "red",
            "ERP Settlement Only": "gray",
        }[status] || "gray";
        return [__(status || "Unknown"), color, `status,=,${status}`];
    },
};
