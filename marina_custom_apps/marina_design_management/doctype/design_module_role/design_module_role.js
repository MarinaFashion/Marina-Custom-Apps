/* Dynamic role configuration — native Frappe permissions remain the baseline. */
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
            __("Choose an enabled Manager role in the reporting hierarchy. New roles require a manager; reporting does not grant approval permissions."));
        frm.set_df_property("scope", "description",
            __("All grants visibility, not edit or approval authority. DocType and Workflow Action permissions must also be configured."));
        if (frm.doc.role_name === "Administrator") {
            frm.set_df_property("reports_to_role", "read_only", true);
        }
        if (frm.is_new()) {
            frm.dashboard.set_headline_alert(
                __("New module roles use the restricted Marina Design Participant ERPNext role. Configure permissions, save the role, then assign users in Design Management Settings."),
                "blue"
            );
        }
    }
});
