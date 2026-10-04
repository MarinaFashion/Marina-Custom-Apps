frappe.ui.form.on("POS Bank Import", {
    refresh(frm) {
        const enabled = cint(frm.doc.tool_enabled);
        const importing = frm.doc.status === "Importing";

        if (!enabled) {
            frm.set_intro(
                __("The Bank Import Tool is disabled. Standard ERPNext Data Import is unchanged and remains available."),
                "orange"
            );
        } else if (importing) {
            frm.set_intro(__("Bank import is running in the background. This page will refresh when it finishes."), "blue");
            pos_bank_import_poll(frm);
        } else {
            frm.set_intro(
                __("Upload the Bank XLSX file, validate it, then run Add + Update. Existing records are matched by the reconciliation key."),
                "blue"
            );
        }

        if (enabled && frm.doc.import_file && !importing) {
            frm.add_custom_button(__("Validate File"), () => pos_bank_import_validate(frm));
            const import_btn = frm.add_custom_button(
                __("Import Add + Update"),
                () => pos_bank_import_start(frm)
            );
            import_btn.addClass("btn-primary");
        }

        if (!importing) {
            frm.add_custom_button(__("Clear Summary"), () => {
                frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_import.pos_bank_import.clear_summary",
                    freeze: true,
                    freeze_message: __("Clearing import summary..."),
                }).then(() => frm.reload_doc());
            });
        }

        if (frappe.user_roles.includes("System Manager")) {
            frm.add_custom_button(
                enabled ? __("Disable Import Tool") : __("Enable Import Tool"),
                () => {
                    const target = enabled ? 0 : 1;
                    const message = enabled
                        ? __("Disable the Bank Import Tool and remove its POS Reconciliation workspace shortcut? Existing Bank POS records and standard ERPNext Data Import will not be changed.")
                        : __("Enable the Bank Import Tool and restore its POS Reconciliation workspace shortcut?");
                    frappe.confirm(message, () => {
                        frappe.call({
                            method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_import.pos_bank_import.toggle_tool",
                            args: { enabled: target },
                            freeze: true,
                        }).then(() => frm.reload_doc());
                    });
                },
                __("Tool")
            );
        }
    },

    import_file(frm) {
        if (frm.doc.import_file) frm.set_value("status", "Ready");
    },
});

function pos_bank_import_validate(frm) {
    const run = () => frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_import.pos_bank_import.validate_file",
        args: { file_url: frm.doc.import_file },
        freeze: true,
        freeze_message: __("Validating Bank file..."),
    }).then((r) => {
        const s = r.message || {};
        frappe.msgprint({
            title: __("Bank File Validation"),
            indicator: cint(s.error_records || 0) || cint(s.conflict_records || 0) ? "orange" : "green",
            message: __("Rows: {0}<br>New: {1}<br>Updates: {2}<br>Unchanged: {3}<br>Conflicts: {4}<br>Errors: {5}<br>Compact dates converted: {6}", [
                s.total_rows || 0, s.new_records || 0, s.update_records || 0,
                s.unchanged_records || 0, s.conflict_records || 0,
                s.error_records || 0, s.date_conversions || 0
            ]),
        });
        return frm.reload_doc();
    });
    if (frm.is_dirty()) return frm.save().then(run);
    return run();
}

function pos_bank_import_start(frm) {
    const run = () => frappe.confirm(
        __("Start Add + Update import? Valid rows will be imported. Conflicts and invalid rows will be skipped and listed in the result."),
        () => {
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_import.pos_bank_import.start_bank_import",
                args: { file_url: frm.doc.import_file },
                freeze: true,
                freeze_message: __("Queueing Bank import..."),
            }).then(() => {
                frappe.show_alert({ message: __("Bank import started"), indicator: "blue" });
                frm.reload_doc().then(() => pos_bank_import_poll(frm));
            });
        }
    );
    if (frm.is_dirty()) return frm.save().then(run);
    return run();
}

function pos_bank_import_poll(frm) {
    if (frm.__pos_bank_import_polling) return;
    frm.__pos_bank_import_polling = true;

    const poll = () => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.pos_bank_import.pos_bank_import.get_status",
        }).then((r) => {
            const s = r.message || {};
            if (s.status === "Importing") {
                setTimeout(poll, 2000);
                return;
            }
            frm.__pos_bank_import_polling = false;
            frm.reload_doc().then(() => {
                frappe.msgprint({
                    title: __("Bank Import Finished"),
                    indicator: s.status === "Completed" ? "green" : "orange",
                    message: __("Status: {0}<br>Total rows: {1}<br>Inserted: {2}<br>Updated: {3}<br>Unchanged: {4}<br>Skipped: {5}<br>Errors: {6}<br>Conflicts: {7}", [
                        s.status || "", s.total_rows || 0, s.inserted_records || 0,
                        s.updated_records || 0, s.unchanged_records || 0,
                        s.skipped_records || 0, s.error_records || 0,
                        s.conflict_records || 0
                    ]),
                });
            });
        }).catch(() => { frm.__pos_bank_import_polling = false; });
    };
    setTimeout(poll, 1500);
}
