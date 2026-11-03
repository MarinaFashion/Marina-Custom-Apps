/* Release 7: per-row metadata-backed Autocomplete field mapping (Frappe v15). */
frappe.ui.form.on("Design Management Settings", {
    setup(frm) {
        frm.set_query("user", "module_user_roles", () => ({
            query:"marina_custom_apps.design_management.security.participants.search_participant_users"
        }));
        frm.set_query("user", "mood_board_base_team", (doc, cdt, cdn) => ({
            query:"marina_custom_apps.design_management.security.participants.search_participant_users",
            filters:{module_role:locals[cdt]?.[cdn]?.module_role||""}
        }));
    },
    onload(frm) { marina_mapping_initialize(frm); },
    refresh(frm) { marina_mapping_initialize(frm); }
});

frappe.ui.form.on("Design Item Field Mapping", {
    source_doctype(frm, cdt, cdn) {
        if (!locals[cdt]?.[cdn]) return;
        // Do not retain a field name belonging to another source DocType.
        frappe.model.set_value(cdt, cdn, "source_field", "");
        marina_mapping_load(frm).then(() => {
            const grid_row = frm.fields_dict.item_field_mappings?.grid?.grid_rows_by_docname?.[cdn];
            if (grid_row) marina_mapping_apply_row(frm, grid_row);
        }).catch(() => {});
    },
    form_render(frm, cdt, cdn) {
        marina_mapping_load(frm).then(() => {
            const grid_row = frm.fields_dict.item_field_mappings?.grid?.grid_rows_by_docname?.[cdn];
            if (grid_row) marina_mapping_apply_row(frm, grid_row);
        }).catch(() => {});
    }
});

function marina_mapping_initialize(frm) {
    if (!frm.__marina_mapping_listener) {
        frm.__marina_mapping_listener = true;
        frm.wrapper.on("grid-row-render.marina-item-mapping", (event, grid_row) => {
            if (grid_row?.doc?.doctype !== "Design Item Field Mapping") return;
            marina_mapping_load(frm).then(() => marina_mapping_apply_row(frm, grid_row)).catch(() => {});
        });
    }
    marina_mapping_load(frm).then(() => marina_mapping_initialize_columns(frm)).catch(() => {});
}

function marina_mapping_load(frm) {
    if (frm.__marina_mapping_options) return Promise.resolve(frm.__marina_mapping_options);
    if (!frm.__marina_mapping_promise) {
        frm.__marina_mapping_promise = frappe.call({
            method: "marina_custom_apps.design_management.item_field_mapping.get_item_mapping_field_options"
        }).then(({message}) => {
            if (!message?.sources || !Array.isArray(message.targets)) {
                throw new Error(__("Item mapping field options are unavailable."));
            }
            frm.__marina_mapping_options = message;
            return message;
        }).catch(error => {
            frm.__marina_mapping_promise = null;
            frappe.show_alert({
                message: __("Unable to load Item mapping fields. Check server permissions / Error Log."),
                indicator: "red"
            });
            throw error;
        });
    }
    return frm.__marina_mapping_promise;
}

function marina_mapping_choices(records) {
    // Autocomplete suggestions are dynamic; Frappe Select's metadata validation
    // rejects any non-static choice even if JS added it in a grid row.
    return [...new Set((records || []).map(r => r.fieldname).filter(Boolean))];
}

function marina_mapping_initialize_columns(frm) {
    const grid = frm.fields_dict.item_field_mappings?.grid;
    if (!grid || !frm.__marina_mapping_options) return;
    // Autocomplete choices belong in the control suggestion dataset, never
    // in DocField.options. Avoid refreshing the entire grid.
    (grid.grid_rows || []).forEach(row => marina_mapping_apply_row(frm, row));
}

function marina_mapping_apply_row(frm, grid_row) {
    if (!grid_row?.doc || !frm.__marina_mapping_options) return;
    const choices = {
        source_field: marina_mapping_choices(
            frm.__marina_mapping_options.sources[grid_row.doc.source_doctype] || []),
        target_field: marina_mapping_choices(frm.__marina_mapping_options.targets)
    };
    for (const [fieldname, suggestions] of Object.entries(choices)) {
        // Only target options can be shared across the grid. Each source row
        // keeps its own metadata options, even after another row is edited.
        const inline = grid_row.columns?.[fieldname]?.field;
        const expanded = grid_row.grid_form?.fields_dict?.[fieldname];
        for (const control of [inline, expanded]) {
            if (!control) continue;
            // ControlAutocomplete.set_data updates suggestions without modifying
            // DocField Options (which must be a string in Frappe v15).
            if (typeof control.set_data === "function") control.set_data(suggestions);
        }
    }
}
