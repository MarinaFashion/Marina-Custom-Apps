frappe.listview_settings["POS Reconciliation Record"] = {
    add_fields: [
        "match_status",
        "resolution_status",
        "before_integration",
        "finance_review_status",
        "bank_statement_status",
        "settlement_number",
    ],

    get_indicator(doc) {
        if (["Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"].includes(doc.match_status) && doc.finance_review_status === "Needs Investigation") {
            return [__("Needs Investigation"), "orange", "finance_review_status,=,Needs Investigation"];
        }
        if (["Bank Only - Settled", "Bank Only - Not Settled", "Bank Only"].includes(doc.match_status) && doc.finance_review_status === "Checked & Approved") {
            return [__("Finance Approved"), "blue", "finance_review_status,=,Checked & Approved"];
        }
        if (doc.resolution_status === "Manually Cleared") {
            return [__("Manually Cleared"), "blue", "resolution_status,=,Manually Cleared"];
        }
        if (doc.match_status === "Fully Matching") {
            return [__("Fully Matching"), "green", "match_status,=,Fully Matching"];
        }
        if (doc.match_status === "Matching Not Settled") {
            return [__("Matching Not Settled"), "blue", "match_status,=,Matching Not Settled"];
        }
        if (doc.match_status === "Discrepancy") {
            return [__("Discrepancy"), "orange", "match_status,=,Discrepancy"];
        }
        if (doc.match_status === "Bank Only - Settled") {
            return [__("Bank Only - Settled"), "blue", "match_status,=,Bank Only - Settled"];
        }
        if (doc.match_status === "Bank Only - Not Settled" || doc.match_status === "Bank Only") {
            return [__("Bank Only - Not Settled"), "orange", "match_status,=,Bank Only - Not Settled"];
        }
        return [__("Alhamrani Only"), "purple", "match_status,=,Alhamrani Only"];
    },

};
