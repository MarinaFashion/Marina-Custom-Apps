/* User pickers in internal workflow records must use the same ERPNext
   participant-role filter. Historical links are never rewritten. */
frappe.ui.form.on("Design Milestone Execution", {
    setup(frm) {
        ["current_custodian","completed_by"].forEach(fieldname => {
            frm.set_query(fieldname, () => ({
                query:"marina_custom_apps.design_management.security.participants.search_participant_users"
            }));
        });
    },
    refresh(frm) {
        // Workflow fields remain protected: never enable direct form Save.
        if (frm.is_new() || !(frappe.session.user === "Administrator" ||
                frappe.user.has_role("System Manager"))) return;
        frm.add_custom_button(__("Correct Dates"), () => {
            const isCompleted = frm.doc.status === "Completed";
            const fields = [
                {
                    fieldtype: "Date", fieldname: "target_date",
                    label: __("Target Date"), reqd: 1,
                    default: frm.doc.due_date
                }
            ];
            if (isCompleted) {
                fields.push({
                    fieldtype: "Datetime", fieldname: "completed_on",
                    label: __("Completed On"), reqd: 1,
                    default: frm.doc.completed_on
                });
            }
            fields.push({
                fieldtype: "Small Text", fieldname: "reason",
                label: __("Correction Reason"), reqd: 1,
                description: __("10–500 characters. Changes are recorded in Custody Events.")
            });
            const dialog = new frappe.ui.Dialog({
                title: __("Correct Milestone Execution Dates"),
                fields,
                primary_action_label: __("Save Correction"),
                primary_action(values) {
                    const reason = (values.reason || "").trim();
                    if (reason.length < 10 || reason.length > 500) {
                        frappe.msgprint(__("Correction reason must be 10–500 characters."));
                        return;
                    }
                    frappe.call({
                        method: "marina_custom_apps.design_management.clean_milestones.execution_corrections.correct_execution_dates",
                        type: "POST",
                        args: {
                            execution_name: frm.doc.name,
                            target_date: values.target_date,
                            completed_on: isCompleted ? values.completed_on : "",
                            reason,
                            expected_last_action_on: frm.doc.last_action_on
                                ? String(frm.doc.last_action_on) : ""
                        },
                        freeze: true,
                        callback({message}) {
                            if (!message) return;
                            dialog.hide();
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __("Execution dates corrected and audited"),
                                indicator: "green"
                            });
                        }
                    });
                }
            });
            dialog.show();
        }, __("Corrections"));
    }
});
