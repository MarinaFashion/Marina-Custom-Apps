frappe.ui.form.on("Design User Permission", {
    refresh(frm) {
        if (frm.is_new() || !frappe.user.has_role("System Manager")) return;

        frm.add_custom_button(__("Fill Operational Test Access"), () => {
            frappe.confirm(
                __("Fill the two tables with operational test permissions for this user? Review all settings before saving. No delete or security-management rights will be granted."),
                () => {
                    const editable = new Set([
                        "Mood Board", "Design Code", "Design Document",
                        "Design Cost Breakdown"
                    ]);
                    const viewable = new Set([
                        "Design Milestone Type", "Design Milestone Plan Entry",
                        "Design Milestone Execution", "Design Document Type",
                        "Design Item Creation", "Marina Pantone",
                        "Marina Fashion Category", "Factory List",
                    ]);
                    for (const row of frm.doc.document_permissions || []) {
                        const edit = editable.has(row.resource_doctype);
                        const view = edit || viewable.has(row.resource_doctype);
                        row.read = view ? 1 : 0;
                        row.create = edit ? 1 : 0;
                        row.write = edit ? 1 : 0;
                        row.delete = 0;
                    }
                    const operational = new Set([
                        "Assign Milestones", "Advance Milestone Step",
                        "Publish Document", "Create ERPNext Items",
                        "Return to Milestone", "Assign Team Tasks",
                        "Reassign Team Tasks", "Send Discussion Message",
                        "Upload Discussion Attachment",
                    ]);
                    for (const row of frm.doc.action_permissions || []) {
                        row.access = operational.has(row.action_key) ? "Allowed" : "Not Allowed";
                    }
                    frm.refresh_field("document_permissions");
                    frm.refresh_field("action_permissions");
                    frm.dirty();
                    frappe.show_alert({
                        message: __("Review the configuration, enable the profile, then Save."),
                        indicator: "orange"
                    }, 8);
                }
            );
        }, __("Presets"));

        frm.add_custom_button(__("Reset To No Access"), () => {
            frappe.confirm(__("Reset all entries to Not Allowed? Changes will not be saved automatically."), () => {
                for (const row of frm.doc.document_permissions || []) {
                    for (const field of ["read", "create", "write", "delete"])
                        row[field] = 0;
                }
                for (const row of frm.doc.action_permissions || []) {
                    row.access = "Not Allowed";
                }
                frm.refresh_field("document_permissions");
                frm.refresh_field("action_permissions");
                frm.dirty();
            });
        }, __("Presets"));

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
