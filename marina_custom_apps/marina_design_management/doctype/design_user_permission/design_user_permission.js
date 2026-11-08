frappe.ui.form.on("Design User Permission", {
    setup(frm) {
        frm.set_query("user", () => ({
            query: "marina_custom_apps.design_management.security.participants.search_participant_users"
        }));
    },
    refresh(frm) {
        marina_render_permission_matrices(frm);
        if (!frappe.user.has_role("System Manager") && frappe.session.user !== "Administrator") return;

        frm.add_custom_button(__("Insert All Documents & Actions"), async () => {
            try {
                const response = await frappe.call({
                    method: "marina_custom_apps.design_management.security.user_permissions.permission_catalog"
                });
                const catalog = response.message || {};
                const existingDocs = new Set((frm.doc.document_permissions || [])
                    .map(row => row.resource_doctype).filter(Boolean));
                const existingActions = new Set((frm.doc.action_permissions || [])
                    .map(row => row.action_key).filter(Boolean));
                let addedDocs = 0;
                let addedActions = 0;
                for (const name of catalog.documents || []) {
                    if (existingDocs.has(name)) continue;
                    frm.add_child("document_permissions", {
                        resource_doctype: name, read: 0, create: 0, write: 0, delete: 0
                    });
                    existingDocs.add(name);
                    addedDocs++;
                }
                for (const action of catalog.actions || []) {
                    if (existingActions.has(action.name)) continue;
                    frm.add_child("action_permissions", {
                        action_key: action.name, access: "Not Allowed"
                    });
                    existingActions.add(action.name);
                    addedActions++;
                }
                marina_render_permission_matrices(frm);
                if (addedDocs || addedActions) frm.dirty();
                frappe.show_alert({
                    message: __("{0} documents and {1} actions inserted. Unchecked/Not Allowed entries are discarded when saved.", [addedDocs, addedActions]),
                    indicator: "blue"
                }, 9);
            } catch (error) {
                frappe.msgprint(__("Unable to load the Design permission catalog."));
            }
        });

        if (frm.is_new()) return;

        frm.add_custom_button(__("View Effective Permissions"), () => {
            if (frm.is_dirty()) {
                frappe.msgprint(__("Save changes before requesting a server-side permission preview."));
                return;
            }
            frappe.call({
                method: "marina_custom_apps.design_management.security.user_permissions.preview_user_permissions",
                args: {user: frm.doc.user},
                callback(r) {
                    const data = r.message || {};
                    let lines = [];
                    for (const item of data.documents || []) {
                        const grants = Object.entries(item.rights || {})
                            .filter(([_, value]) => value.effective)
                            .map(([name]) => name).join(", ") || __("None");
                        lines.push("<li><b>" + frappe.utils.escape_html(item.doctype)
                            + "</b>: " + frappe.utils.escape_html(grants) + "</li>");
                    }
                    const body = "<p>" + __("Effective document access, including native ERPNext role restrictions:")
                        + "</p><ul>" + lines.join("") + "</ul><p>"
                        + __("Action and custody checks also apply server-side.") + "</p>";
                    frappe.msgprint({title: __("Document Permission Preview"), message: body, wide: true});
                }
            });
        });
    }
});


/* User-centric permission matrices, backed by the original child tables.
   Rendering never grants permissions. Unsaved changes remain in frm.doc until
   Save validates and drops empty/Not Allowed rows server-side. */
function marina_render_permission_matrices(frm) {
    const escape = frappe.utils.escape_html;
    const canEdit = Boolean(frm.has_perm("write") || (frm.is_new() && frm.has_perm("create")));
    const dArea = frm.fields_dict.document_permission_matrix?.$wrapper;
    const aArea = frm.fields_dict.action_permission_matrix?.$wrapper;
    if (!dArea?.length || !aArea?.length) return;

    const docs = (frm.doc.document_permissions || []).filter(row => row.resource_doctype);
    const actions = (frm.doc.action_permissions || []).filter(row => row.action_key);
    const types = [
        ["read", __("Read")], ["create", __("Create")],
        ["write", __("Edit")], ["delete", __("Delete")]
    ];
    const head = '<th style="position:sticky;left:0;z-index:3;background:var(--card-bg,#fff);min-width:230px">' +
        __("Document") + '</th>' + types.map(([key,label]) =>
        '<th class="text-center" style="min-width:105px">' + escape(label) + '</th>').join("");
    const body = docs.map(row => '<tr><th style="position:sticky;left:0;z-index:2;background:var(--card-bg,#fff);white-space:nowrap">' +
        escape(row.resource_doctype) + '</th>' + types.map(([key]) =>
        '<td class="text-center"><input type="checkbox" class="mdm-document-check" ' +
        'data-row="' + escape(row.name) + '" data-field="' + key + '" ' +
        (Number(row[key]) ? "checked " : "") +
        (!canEdit ? "disabled " : "") +
        'aria-label="' + escape(row.resource_doctype + " / " + key) +
        '"></td>').join("") + '</tr>').join("");
    dArea.html(
        '<p class="small text-muted">' +
        escape(__("Checked = permitted, unchecked = denied. Rows with no checked permissions disappear after Save. Insert All adds missing documents.")) +
        '</p><div style="overflow:auto;max-height:510px;border:1px solid var(--border-color,#ddd);border-radius:6px">' +
        '<table class="table table-bordered table-sm" style="min-width:660px;margin:0">' +
        '<thead style="position:sticky;top:0;z-index:4;background:var(--card-bg,#fff)"><tr>' + head +
        '</tr></thead><tbody>' + (body || '<tr><td colspan="5" class="text-muted text-center p-3">' +
        escape(__("No document entries. Use Insert All Documents & Actions.")) + '</td></tr>') +
        '</tbody></table></div>'
    );
    dArea.off("change.marinaPermission").on("change.marinaPermission", ".mdm-document-check", function() {
        const row = (frm.doc.document_permissions || []).find(r => r.name === $(this).attr("data-row"));
        const field = $(this).attr("data-field");
        if (!row || !["read","create","write","delete"].includes(field) || !canEdit) return;
        frappe.model.set_value(row.doctype, row.name, field, $(this).prop("checked") ? 1 : 0);
        frm.dirty();
    });

    const choices = [
        ["Not Allowed", __("Not Allowed")], ["Allowed", __("Allowed")],
        ["Custody Only", __("Custody Only")]
    ];
    const aHead = '<th style="position:sticky;left:0;z-index:3;background:var(--card-bg,#fff);min-width:230px">' +
        escape(__("Action")) + '</th>' + choices.map(([key,label]) =>
        '<th class="text-center" style="min-width:115px">' + escape(label) + '</th>').join("");
    const aBody = actions.map(row => {
        const onlyMilestone = row.action_key === "Advance Milestone Step";
        const selected = row.access || "Not Allowed";
        return '<tr><th style="position:sticky;left:0;z-index:2;background:var(--card-bg,#fff);white-space:nowrap">' +
            escape(row.action_key) + '</th>' + choices.map(([key]) => {
                const disabled = !canEdit || (key === "Custody Only" && !onlyMilestone);
                return '<td class="text-center"><input type="radio" class="mdm-action-choice" ' +
                    'name="mdm-action-' + escape(row.name) + '" data-row="' + escape(row.name) +
                    '" value="' + escape(key) + '" ' + (selected === key ? "checked " : "") +
                    (disabled ? "disabled " : "") + 'aria-label="' +
                    escape(row.action_key + " / " + key) + '"></td>';
            }).join("") + '</tr>';
    }).join("");
    aArea.html(
        '<p class="small text-muted">' +
        escape(__("Select one permission per action. Custody Only applies to Advance Milestone Step. Not Allowed rows disappear after Save.")) +
        '</p><div style="overflow:auto;max-height:510px;border:1px solid var(--border-color,#ddd);border-radius:6px">' +
        '<table class="table table-bordered table-sm" style="min-width:700px;margin:0">' +
        '<thead style="position:sticky;top:0;z-index:4;background:var(--card-bg,#fff)"><tr>' + aHead +
        '</tr></thead><tbody>' + (aBody || '<tr><td colspan="4" class="text-muted text-center p-3">' +
        escape(__("No action entries. Use Insert All Documents & Actions.")) + '</td></tr>') +
        '</tbody></table></div>'
    );
    aArea.off("change.marinaPermission").on("change.marinaPermission", ".mdm-action-choice", function() {
        const row = (frm.doc.action_permissions || []).find(r => r.name === $(this).attr("data-row"));
        const choice = $(this).val();
        if (!row || !canEdit || !["Not Allowed","Allowed","Custody Only"].includes(choice)) return;
        if (choice === "Custody Only" && row.action_key !== "Advance Milestone Step") return;
        frappe.model.set_value(row.doctype, row.name, "access", choice);
        frm.dirty();
    });
}
