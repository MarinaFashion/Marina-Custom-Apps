frappe.ui.form.on("Marina Bank Statement Import", {
    refresh(frm) {
        if (frm.is_new()) return;

        const importing = frm.doc.status === "Importing";
        if (importing) {
            frm.set_intro(__("Statement import is running in the background."), "blue");
            marina_statement_poll(frm);
            return;
        }

        if (frm.doc.import_file && ["Draft", "Validated", "Completed with Errors", "Failed"].includes(frm.doc.status || "Draft")) {
            frm.add_custom_button(__("Validate Statement"), () => marina_statement_validate(frm));
            const btn = frm.add_custom_button(__("Import Statement"), () => marina_statement_import(frm));
            btn.addClass("btn-primary");
        }

        frm.add_custom_button(__("Statement Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction", {statement_import: frm.doc.name});
        }, __("View"));
        frm.add_custom_button(__("Unreconciled Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction", {
                statement_import: frm.doc.name,
                reconciliation_status: "Unreconciled",
            });
        }, __("View"));
    },
});

function marina_statement_validate(frm) {
    return frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.validate_statement",
        args: {name: frm.doc.name},
        freeze: true,
        freeze_message: __("Validating SNB statement..."),
    }).then((r) => {
        const s = r.message || {};
        frappe.msgprint({
            title: __("Statement Validation"),
            indicator: cint(s.error_records || 0) ? "orange" : "green",
            message: __("Rows: {0}<br>New: {1}<br>Duplicates: {2}<br>POS lines: {3}<br>Other lines: {4}<br>Errors: {5}", [
                s.total_rows || 0, s.new_records || 0, s.duplicate_records || 0,
                s.pos_statement_lines || 0, s.other_statement_lines || 0, s.error_records || 0
            ]),
        });
        return frm.reload_doc();
    });
}

function marina_statement_import(frm) {
    frappe.confirm(__("Import this statement into Marina Bank Statement Transaction? Existing identical source lines will be skipped."), () => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.start_statement_import",
            args: {name: frm.doc.name},
            freeze: true,
            freeze_message: __("Queueing statement import..."),
        }).then(() => frm.reload_doc().then(() => marina_statement_poll(frm)));
    });
}

function marina_statement_poll(frm) {
    if (frm.__marina_statement_polling) return;
    frm.__marina_statement_polling = true;
    const poll = () => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.get_status",
            args: {name: frm.doc.name},
        }).then((r) => {
            const s = r.message || {};
            if (s.status === "Importing") {
                setTimeout(poll, 2000);
                return;
            }
            frm.__marina_statement_polling = false;
            frm.reload_doc().then(() => {
                frappe.msgprint({
                    title: __("Statement Import Finished"),
                    indicator: s.status === "Completed" ? "green" : "orange",
                    message: __("Status: {0}<br>Inserted: {1}<br>Duplicates: {2}<br>Errors: {3}", [
                        s.status || "", s.inserted_records || 0, s.duplicate_records || 0, s.error_records || 0
                    ]),
                });
            });
        }).catch(() => { frm.__marina_statement_polling = false; });
    };
    setTimeout(poll, 1200);
}
