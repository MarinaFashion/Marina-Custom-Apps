/* User pickers in internal workflow records must use the same ERPNext
   participant-role filter. Historical links are never rewritten. */
frappe.ui.form.on("Design Milestone Plan Entry", {
    setup(frm) {
        ["selected_by"].forEach(fieldname => {
            frm.set_query(fieldname, () => ({
                query:"marina_custom_apps.design_management.security.participants.search_participant_users"
            }));
        });
    }
});
