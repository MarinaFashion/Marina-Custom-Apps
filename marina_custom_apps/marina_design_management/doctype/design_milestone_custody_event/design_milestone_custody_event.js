/* User pickers in internal workflow records must use the same ERPNext
   participant-role filter. Historical links are never rewritten. */
frappe.ui.form.on("Design Milestone Custody Event", {
    setup(frm) {
        ["from_user","to_user","performed_by"].forEach(fieldname => {
            frm.set_query(fieldname, () => ({
                query:"marina_custom_apps.design_management.security.participants.search_participant_users"
            }));
        });
    }
});
