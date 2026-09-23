frappe.ui.form.on("Journal Entry", {
    setup(frm) {
        configure_bilingual_account_query(frm);
    },

    refresh(frm) {
        configure_bilingual_account_query(frm);
    },

    company(frm) {
        configure_bilingual_account_query(frm);
    },
});


function configure_bilingual_account_query(frm) {
    frm.set_query("account", "accounts", () => ({
        query: "marina_custom_apps.accounting.bilingual_account_search.bilingual_account_query",
        filters: {
            company: frm.doc.company || "",
            is_group: 0,
        },
    }));
}
