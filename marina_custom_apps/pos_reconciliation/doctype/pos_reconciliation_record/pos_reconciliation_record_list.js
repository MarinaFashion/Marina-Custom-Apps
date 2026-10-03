function selected_record_names(listview) {
    return listview.get_checked_items().map((row) => row.name);
}

function finance_review_selected(listview, decision) {
    const names = selected_record_names(listview);
    if (!names.length) {
        frappe.msgprint(__("Select at least one reconciliation record."));
        return;
    }

    const approved = decision === "Checked & Approved";
    frappe.prompt(
        [{
            fieldname: "note",
            label: __("Finance Review Note"),
            fieldtype: "Small Text",
            reqd: !approved,
            default: approved ? __("Finance checked and approved against books") : "",
        }],
        (values) => {
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.finance_review.review_selected_records",
                args: { record_names: names, decision: decision, note: values.note },
                freeze: true,
                freeze_message: __("Updating Finance review..."),
            }).then(() => listview.refresh());
        },
        __("Finance Review"),
        approved ? __("Approve") : __("Flag")
    );
}

frappe.listview_settings["POS Reconciliation Record"] = {
    add_fields: [
        "match_status",
        "resolution_status",
        "before_integration",
        "finance_review_status",
        "settlement_number",
    ],

    get_indicator(doc) {
        if (doc.match_status === "Bank Only" && doc.finance_review_status === "Needs Investigation") {
            return [__("Needs Investigation"), "orange", "finance_review_status,=,Needs Investigation"];
        }
        if (doc.match_status === "Bank Only" && doc.finance_review_status === "Checked & Approved") {
            return [__("Finance Approved"), "blue", "finance_review_status,=,Checked & Approved"];
        }
        if (doc.resolution_status === "Manually Cleared") {
            return [__("Manually Cleared"), "blue", "resolution_status,=,Manually Cleared"];
        }
        if (doc.match_status === "Matching") {
            return [__("Matching"), "green", "match_status,=,Matching"];
        }
        if (doc.match_status === "Discrepancy") {
            return [__("Discrepancy"), "orange", "match_status,=,Discrepancy"];
        }
        if (doc.match_status === "Bank Only") {
            return [__("Bank Only"), "red", "match_status,=,Bank Only"];
        }
        return [__("Alhamrani Only"), "purple", "match_status,=,Alhamrani Only"];
    },

    onload(listview) {
        listview.page.add_actions_menu_item(__("Finance: Checked & Approved"), () => {
            finance_review_selected(listview, "Checked & Approved");
        });

        listview.page.add_actions_menu_item(__("Finance: Needs Investigation"), () => {
            finance_review_selected(listview, "Needs Investigation");
        });

        listview.page.add_actions_menu_item(__("Finance: Reset Review"), () => {
            const names = selected_record_names(listview);
            if (!names.length) {
                frappe.msgprint(__("Select at least one reconciliation record."));
                return;
            }
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.finance_review.reset_selected_records",
                args: { record_names: names },
                freeze: true,
                freeze_message: __("Resetting Finance review..."),
            }).then(() => listview.refresh());
        });
    },
};
