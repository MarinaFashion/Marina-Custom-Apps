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
            frm.set_intro(__("Approved preview only. HRMS posting is NOT enabled."), "orange");
        } else {
            frm.set_intro(__("PREVIEW: no Leave Allocation or Leave Ledger changes will occur."), "blue");
        }
    }
});
