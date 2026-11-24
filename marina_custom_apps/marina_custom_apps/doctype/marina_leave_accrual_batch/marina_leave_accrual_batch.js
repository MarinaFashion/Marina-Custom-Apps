frappe.ui.form.on("Marina Leave Accrual Batch", {
    refresh(frm) {
        if (frm.is_new()) {
            frm.set_intro(__("Save the company and completed month-end date, then generate accrual candidates."), "blue");
            return;
        }
        if (frm.doc.status === "Draft" || frm.doc.status === "Calculated") {
            frm.add_custom_button(__("Generate / Refresh Candidates"), () => {
                frappe.confirm(
                    __("Refresh the monthly figures from current HRMS data? Existing batch rows will be replaced."),
                    () => frappe.call({
                        method: "marina_custom_apps.marina_custom_apps.doctype.marina_leave_accrual_batch.marina_leave_accrual_batch.generate_batch",
                        args: {name: frm.doc.name},
                        freeze: true,
                        freeze_message: __("Calculating monthly accrual...")
                    }).then(() => frm.reload_doc())
                );
            });
        }
        if (frm.doc.status === "Calculated") {
            frm.add_custom_button(__("Approve Preview Batch"), () => {
                const warnings = (frm.doc.employees || []).filter(
                    row => row.status === "Needs Review"
                ).length;
                const message = warnings
                    ? __("{0} employees have review warnings. Approval confirms you have reviewed them; no leave will be posted. Continue?", [warnings])
                    : __("Approve this calculated snapshot? No Leave Allocations or Ledger entries will be created.");
                frappe.confirm(message, () => {
                    frappe.call({
                        method: "marina_custom_apps.marina_custom_apps.doctype.marina_leave_accrual_batch.marina_leave_accrual_batch.approve_batch",
                        args: {name: frm.doc.name, confirm_warnings: warnings > 0 ? 1 : 0},
                        freeze: true
                    }).then(() => frm.reload_doc());
                });
            }, __("Actions"));
        }
        if (frm.doc.status === "Approved") {
            frm.add_custom_button(__("Check Posting Readiness"), () => {
                const eligible = (frm.doc.employees || []).filter(row =>
                    row.candidate_credit > 0 && row.status === "Ready for Approval"
                );
                if (!eligible.length) {
                    frappe.msgprint(__("No positive-credit employees to inspect."));
                    return;
                }
                const dialog = new frappe.ui.Dialog({
                    title: __("Read-only Posting Preflight"),
                    fields: [{
                        fieldname: "employee", fieldtype: "Link", options: "Employee",
                        label: __("Employee"), reqd: 1,
                        default: eligible[0].employee
                    }],
                    primary_action_label: __("Run Preflight"),
                    primary_action(values) {
                        const selected = eligible.find(x => x.employee === values.employee);
                        if (!selected) {
                            frappe.msgprint(__("Select a positive-credit employee in this batch."));
                            return;
                        }
                        frappe.call({
                            method: "marina_custom_apps.marina_leave_management.posting_preflight.preview_employee_posting",
                            args: {batch_name: frm.doc.name, employee: values.employee},
                            freeze: true
                        }).then(res => {
                            dialog.hide();
                            const d = res.message || {};
                            const blockers = (d.blocking_reasons || []).map(s =>
                                "<li>" + frappe.utils.escape_html(s) + "</li>"
                            ).join("");
                            const warnings = (d.warnings || []).map(s =>
                                "<li>" + frappe.utils.escape_html(s) + "</li>"
                            ).join("");
                            frappe.msgprint({
                                title: __("Posting Preflight — No Changes"),
                                indicator: "orange",
                                message:
                                    "<p><b>" + __("Employee") + ":</b> " +
                                    frappe.utils.escape_html(values.employee) + "</p>" +
                                    "<p><b>" + __("Monthly Credit") + ":</b> " +
                                    frappe.utils.escape_html(String(d.monthly_credit ?? "")) + "</p>" +
                                    "<p><b>" + __("Blockers") + ":</b></p><ul>" + blockers + "</ul>" +
                                    "<p><b>" + __("Warnings") + ":</b></p><ul>" + warnings + "</ul>" +
                                    "<p><b>" + __("Posting Enabled") + ":</b> No</p>"
                            });
                        });
                    }
                });
                dialog.show();
            }, __("Actions"));
        }
        if (frm.doc.status === "Approved") {
            frm.set_intro(__("Approved preview only. HRMS posting is NOT enabled."), "orange");
        } else {
            frm.set_intro(__("PREVIEW: no Leave Allocation or Leave Ledger changes will occur."), "blue");
        }
    }
});
