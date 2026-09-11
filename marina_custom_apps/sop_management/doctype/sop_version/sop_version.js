frappe.ui.form.on("SOP Version", {
    refresh(frm) {
        render_advanced_html_preview(frm);

        if (frm.is_new()) return;

        if (frm.doc.sop_document) {
            frm.add_custom_button(__("Open SOP Document"), () => {
                frappe.set_route("Form", "SOP Document", frm.doc.sop_document);
            });
        }

        frm.add_custom_button(__("Document Preview"), () => {
            const params = new URLSearchParams({
                doctype: "SOP Version",
                name: frm.doc.name,
                format: "Marina SOP Controlled Document",
                no_letterhead: "1",
                trigger_print: "0"
            });
            window.open(`/printview?${params.toString()}`, "_blank");
        });

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
            (frappe.user.has_role("SOP Manager") || frappe.user.has_role("System Manager") || frappe.session.user === "Administrator")) {
            frm.add_custom_button(__("Publish"), () => {
                frappe.confirm(
                    __("Publish this version and supersede the previous published version?"),
                    () => sop_action(frm, "publish_version")
                );
            }, __("Workflow"));
        }

        const can_manage_version =
            frappe.session.user === "Administrator" ||
            frappe.user.has_role("SOP Manager") ||
            frappe.user.has_role("System Manager");

        if (can_manage_version && frm.doc.status === "Published") {
            frm.add_custom_button(__("Unpublish"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Unpublish SOP Version"),
                    fields: [
                        {
                            fieldname: "reason",
                            fieldtype: "Small Text",
                            label: __("Unpublish Reason"),
                            reqd: 1
                        }
                    ],
                    primary_action_label: __("Unpublish"),
                    primary_action(values) {
                        const reason = (values.reason || "").trim();
                        if (!reason) {
                            frappe.msgprint(__("Unpublish Reason is required."));
                            return;
                        }
                        dialog.hide();
                        frappe.call({
                            method: "marina_custom_apps.sop_management.api.unpublish_version",
                            args: {
                                version_name: frm.doc.name,
                                reason
                            },
                            freeze: true,
                            freeze_message: __("Unpublishing SOP Version..."),
                            callback() {
                                frm.reload_doc();
                            }
                        });
                    }
                });
                dialog.show();
            }, __("Workflow"));
        }

        if (
            can_manage_version &&
            !["Published", "Superseded", "Cancelled"].includes(frm.doc.status)
        ) {
            frm.add_custom_button(__("Cancel Version"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Cancel SOP Version"),
                    fields: [
                        {
                            fieldname: "reason",
                            fieldtype: "Small Text",
                            label: __("Cancellation Reason"),
                            reqd: 1
                        }
                    ],
                    primary_action_label: __("Cancel Version"),
                    primary_action(values) {
                        const reason = (values.reason || "").trim();
                        if (!reason) {
                            frappe.msgprint(__("Cancellation Reason is required."));
                            return;
                        }
                        dialog.hide();
                        frappe.call({
                            method: "marina_custom_apps.sop_management.api.cancel_version",
                            args: {
                                version_name: frm.doc.name,
                                reason
                            },
                            freeze: true,
                            freeze_message: __("Cancelling SOP Version..."),
                            callback() {
                                frm.reload_doc();
                            }
                        });
                    }
                });
                dialog.show();
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
frappe.ui.form.on("SOP Version", {
    content_mode(frm) {
        render_advanced_html_preview(frm);
    },
    html_content(frm) {
        if (frm.doc.content_mode === "Advanced HTML") {
            clearTimeout(frm.__sop_html_preview_timer);
            frm.__sop_html_preview_timer = setTimeout(
                () => render_advanced_html_preview(frm),
                350
            );
        }
    }
});

function render_advanced_html_preview(frm) {
    const field = frm.get_field("html_preview");
    if (!field || !field.$wrapper) return;

    if (frm.doc.content_mode !== "Advanced HTML") {
        field.$wrapper.empty();
        return;
    }

    frappe.call({
        method: "marina_custom_apps.sop_management.api.preview_advanced_html",
        args: { html_content: frm.doc.html_content || "" },
        callback(r) {
            const placeholder = `<span class="text-muted">${__("HTML preview will appear here.")}</span>`;
            field.$wrapper.html(`
                <div class="sop-html-preview border rounded" style="padding:16px;background:var(--card-bg)">
                    ${r.message || placeholder}
                </div>
            `);
        }
    });
}
