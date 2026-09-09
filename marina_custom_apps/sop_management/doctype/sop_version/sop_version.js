frappe.ui.form.on("SOP Version", {
    refresh(frm) {
        if (frm.is_new()) return;

        if (frm.doc.status === "Draft" &&
            (frappe.user.has_role("SOP Editor") || frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager"))) {
            frm.add_custom_button(__("Submit for Review"), () => {
                sop_action(frm, "submit_for_review");
            }, __("Workflow"));
        }

        if (frm.doc.status === "Under Review" &&
            (frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager"))) {
            frm.add_custom_button(__("Approve"), () => {
                sop_action(frm, "approve_version");
            }, __("Workflow"));
        }

        if (frm.doc.status === "Approved" &&
            (frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager"))) {
            frm.add_custom_button(__("Publish"), () => {
                frappe.confirm(
                    __("Publish this version and supersede the previous published version?"),
                    () => sop_action(frm, "publish_version")
                );
            }, __("Workflow"));
        }
    }
});

function sop_action(frm, action) {
    frappe.call({
        method: `marina_custom_apps.sop_management.api.${action}`,
        args: { version_name: frm.doc.name },
        freeze: true,
        callback() {
            frm.reload_doc();
        }
    });
}
