frappe.ui.form.on("Marina Calendar Date", {
    refresh(frm) {
        if (frm.doc.event_count) {
            frm.dashboard.add_indicator(
                __("{0} Event(s)", [frm.doc.event_count]),
                "blue"
            );
        }
        if (!frm.is_new()) {
            frm.add_custom_button(__("New Event for This Date"), () => {
                frappe.new_doc("Marina Calendar Event", {
                    start_date: frm.doc.date,
                    end_date: frm.doc.date,
                    scope: "Company"
                });
            }, __("Calendar"));
        }
    }
});
