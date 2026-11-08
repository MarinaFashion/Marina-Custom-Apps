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
    refresh(frm) {
        marina_mapping_initialize(frm);
        marina_workspace_visibility_matrix(frm);
        marina_individual_permission_link(frm);
    }
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

/* User-centric workspace matrix. The hidden child table is authoritative;
   the HTML matrix is only a convenient editor for explicit user/item choices. */
function marina_workspace_visibility_matrix(frm) {
    const $area=frm.fields_dict.workspace_visibility_matrix?.$wrapper;
    if(!$area?.length)return;
    const esc=frappe.utils.escape_html;
    const admin=frappe.user.has_role("System Manager") || frappe.session.user==="Administrator";
    if(!admin){
        $area.text(__("Only System Manager may edit workspace visibility."));
        return;
    }
    $area.html('<p class="text-muted">'+esc(__("Loading workspace visibility…"))+'</p>');
    frappe.call({
        method:"marina_custom_apps.design_management.workspace_visibility.workspace_user_matrix"
    }).then(({message:data})=>{
        if(!data || !frm.fields_dict.workspace_visibility_matrix)return;
        const users=data.users||[], items=data.items||[];
        const saved=new Map((frm.doc.workspace_user_visibility||[]).map(row=>
            [row.workspace_item+"\u0000"+row.user,row]));
        const header='<th style="position:sticky;left:0;background:#fff;z-index:3;min-width:210px">'+
            esc(__("Workspace Item"))+'</th>'+users.map(u=>
            '<th style="min-width:125px;white-space:nowrap;text-align:center">'+
            esc(u.label)+'</th>').join('');
        const body=items.map(item=>
            '<tr><th style="position:sticky;left:0;background:#fff;z-index:2;white-space:nowrap">'+
            esc(item)+'</th>'+users.map(u=>{
                const rule=saved.get(item+"\u0000"+u.user);
                const checked=rule ? !!Number(rule.visible) : !!data.fallback?.[u.user]?.[item];
                const disabled=frm.has_perm && !frm.has_perm("write");
                return '<td style="text-align:center"><input type="checkbox" class="marina-visibility-check" '+
                    'data-item="'+esc(item)+'" data-user="'+esc(u.user)+'" '+
                    (checked?'checked ':'')+(disabled?'disabled ':'')+
                    'aria-label="'+esc(item+" / "+u.label)+'"></td>';
            }).join('')+'</tr>').join('');
        $area.html('<p class="small text-muted">'+
            esc(__("Checked = show, unchecked = hide. Save Settings to apply changes. Scroll horizontally for more users."))+
            '</p><div style="overflow:auto;max-height:540px;border:1px solid #ddd;border-radius:6px">'+
            '<table class="table table-bordered table-sm" style="width:max-content;min-width:100%;margin:0">'+
            '<thead style="position:sticky;top:0;background:white;z-index:4"><tr>'+header+
            '</tr></thead><tbody>'+body+'</tbody></table></div>');
        $area.off("change.marinaVisibility").on("change.marinaVisibility",".marina-visibility-check",function(){
            const item=$(this).attr("data-item"),user=$(this).attr("data-user");
            const key=item+"\u0000"+user;
            const visible=$(this).prop("checked")?1:0;
            const existing=saved.get(key);
            if(existing){
                frappe.model.set_value(existing.doctype,existing.name,"visible",visible);
            }else{
                const row=frm.add_child("workspace_user_visibility",{
                    workspace_item:item,user,visible
                });
                saved.set(key,row);
                frm.dirty();
            }
        });
    }).catch(()=>{
        $area.text(__("Unable to load workspace visibility. Please retry."));
    });
}


/* Navigation only. Individual permissions live in a separate, admin-controlled
   DocType; workspace visibility and team membership remain on this form. */
function marina_individual_permission_link(frm) {
    const $wrapper = frm.fields_dict.design_user_permission_link?.$wrapper;
    if (!$wrapper?.length) return;
    const admin = frappe.session.user === "Administrator" ||
        frappe.user.has_role("System Manager");
    $wrapper.empty();
    if (!admin) {
        $wrapper.text(__("Only System Manager can configure individual permissions."));
        return;
    }
    const $button = $('<button type="button" class="btn btn-primary btn-sm"></button>')
        .text(__("Manage Design User Permissions"))
        .appendTo($wrapper);
    $button.on("click", () => frappe.set_route("List", "Design User Permission"));
    $('<div class="small text-muted mt-2"></div>')
        .text(__("Documents and Actions are managed per user. Team roles above identify responsibility and custody; workspace visibility remains independent."))
        .appendTo($wrapper);
}
