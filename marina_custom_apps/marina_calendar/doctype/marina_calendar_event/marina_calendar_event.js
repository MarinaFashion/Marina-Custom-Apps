frappe.ui.form.on("Marina Calendar Event", {
    refresh(frm) {
        frm.add_custom_button(__("Open Calendar"), () => {
            frappe.set_route("List", "Marina Calendar Event", "Calendar", "default");
        }, __("Calendar"));

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
    store_trading_status(frm) {
        if (frm.doc.store_trading_status === "Closed") {
            frm.set_value("forecast_relevant", 1);
            frm.set_value("expected_sales_impact", "Negative");
            frm.set_value("impact_strength", "High");
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
