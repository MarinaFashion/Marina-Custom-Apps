frappe.ui.form.on("Marina Calendar Event", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.start_date && frm.doc.end_date) {
            const start = frappe.datetime.str_to_obj(frm.doc.start_date);
            const end = frappe.datetime.str_to_obj(frm.doc.end_date);
            const days = frappe.datetime.get_day_diff(end, start) + 1;
            frm.dashboard.add_indicator(__("{0} Calendar Day(s)", [days]), "blue");
        }
    },
    start_date(frm) {
        if (frm.doc.start_date && !frm.doc.end_date) {
            frm.set_value("end_date", frm.doc.start_date);
        }
    },
    scope(frm) {
        if (frm.doc.scope === "Company") {
            frm.set_value("city", "");
            frm.set_value("branch", "");
        } else if (frm.doc.scope === "City") {
            frm.set_value("branch", "");
        }
    }
});
