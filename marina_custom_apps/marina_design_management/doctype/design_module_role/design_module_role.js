/* Organizational role editor. Individual action/document rights are managed separately. */
frappe.ui.form.on("Design Module Role", {
    onload(frm) {
        frm.set_query("reports_to_role", () => ({
            filters: [
                ["Design Module Role", "enabled", "=", 1],
                ["Design Module Role", "role_type", "=", "Manager"],
                ["Design Module Role", "name", "!=", frm.doc.name || ""]
            ]
        }));
    },
    refresh(frm) {
        if (frm.is_new() && !frm.doc.frappe_role) {
            frm.set_value("frappe_role", "Marina Design Participant");
        }
        frm.set_df_property("frappe_role", "read_only", true);
        frm.set_df_property("reports_to_role", "description",
            __("Organizational reporting and responsibility only. Individual Document and Action permissions are managed in Design User Permission."));
        frm.set_df_property("scope", "description",
            __("Legacy record scope applies only to users not yet migrated to individual permissions."));
        if (frm.doc.role_name === "Administrator") {
            frm.set_df_property("reports_to_role", "read_only", true);
        }
        if (frm.is_new()) {
            frm.dashboard.set_headline_alert(
                __("New organizational roles use the restricted Marina Design Participant ERPNext role. Save the role, assign users in Design Management Settings, and configure each user in Design User Permission."),
                "blue"
            );
        }
    }
});
