frappe.ui.form.on("SOP Document", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Open in SOP Library"), () => {
            frappe.route_options = { sop: frm.doc.name };
            frappe.set_route("sop-library");
        });

        if (frappe.user.has_role("SOP Editor") || frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Create New Version"), () => {
                frappe.call({
                    method: "marina_custom_apps.sop_management.api.create_new_version",
                    args: { sop_document: frm.doc.name },
                    freeze: true,
                    callback(r) {
                        if (r.message) {
                            frappe.set_route("Form", "SOP Version", r.message);
                        }
                    }
                });
            }, __("Actions"));
        }

        if (
            frm.doc.status === "Published" &&
            (frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager"))
        ) {
            frm.add_custom_button(__("Archive SOP"), () => {
                frappe.confirm(
                    __("Archive this SOP and remove it from the active SOP Library?"),
                    () => {
                        frappe.call({
                            method: "marina_custom_apps.sop_management.api.archive_sop",
                            args: { sop_document: frm.doc.name },
                            freeze: true,
                            callback() {
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __("Actions"));
        }
    }
});
