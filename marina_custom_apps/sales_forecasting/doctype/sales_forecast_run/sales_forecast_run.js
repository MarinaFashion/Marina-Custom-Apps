frappe.ui.form.on("Sales Forecast Run", {
    onload(frm) {
        if (frm.is_new()) {
            const today = frappe.datetime.get_today();
            if (!frm.doc.as_of_date) frm.set_value("as_of_date", today);
            if (!frm.doc.forecast_from) frm.set_value("forecast_from", frappe.datetime.add_days(today, 1));
            if (!frm.doc.forecast_to) frm.set_value("forecast_to", frappe.datetime.add_days(today, 90));
        }
    },

    refresh(frm) {
        render_run_indicators(frm);
        if (!frm.is_new()) {
            if (!["Completed", "Queued", "Running"].includes(frm.doc.status)) {
                frm.add_custom_button(__("Run Forecast"), () => queue_forecast(frm), __("Forecast"));
            }
            frm.add_custom_button(__("Data Mart Records"), () => {
                frappe.set_route("List", "Sales Forecast Daily");
            }, __("Forecast"));
            frm.add_custom_button(__("Results"), () => {
                frappe.set_route("List", "Sales Forecast Result", { forecast_run: frm.doc.name });
            }, __("Forecast"));
        }
        if (frm.doc.status === "Completed") render_preview(frm);
    }
});

function render_run_indicators(frm) {
    if (frm.doc.status) {
        const color = { Completed: "green", Failed: "red", Running: "orange", Queued: "blue", Draft: "grey" }[frm.doc.status] || "grey";
        frm.dashboard.add_indicator(__("Status: {0}", [frm.doc.status]), color);
    }
    if (frm.doc.status === "Completed") {
        frm.dashboard.add_indicator(__("Forecast: {0}", [format_currency(frm.doc.forecast_sales, "SAR")]), "blue");
        const actualRows = cint(frm.doc.actual_result_count);
        const resultRows = cint(frm.doc.result_count);
        if (actualRows > 0 && resultRows > 0 && actualRows === resultRows) {
            frm.dashboard.add_indicator(__("Accuracy: {0}%", [flt(frm.doc.accuracy_pct).toFixed(1)]), flt(frm.doc.accuracy_pct) >= 85 ? "green" : "orange");
            frm.dashboard.add_indicator(__("Bias: {0}%", [flt(frm.doc.bias_pct).toFixed(1)]), Math.abs(flt(frm.doc.bias_pct)) <= 5 ? "green" : "red");
        } else if (actualRows > 0) {
            frm.dashboard.add_indicator(__("Actual coverage: {0}/{1}", [actualRows, resultRows]), "orange");
        }
    }
}

function queue_forecast(frm) {
    frappe.call({
        method: "marina_custom_apps.sales_forecasting.api.queue_forecast_run",
        args: { run_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Queueing Marina forecast..."),
        callback(r) {
            if (!r.exc) {
                frappe.show_alert({
                    message: __("Forecast queued. Missing historical Data Mart records will be created automatically."),
                    indicator: "blue"
                });
                poll_run(frm, 0);
            }
        }
    });
}

function poll_run(frm, attempt) {
    if (attempt > 180) return;
    setTimeout(() => {
        frappe.db.get_value("Sales Forecast Run", frm.doc.name, ["status", "result_count"]).then(r => {
            const status = r.message && r.message.status;
            if (["Completed", "Failed"].includes(status)) {
                frm.reload_doc();
            } else {
                poll_run(frm, attempt + 1);
            }
        });
    }, 3000);
}

function render_preview(frm) {
    const wrapper = frm.fields_dict.forecast_preview && frm.fields_dict.forecast_preview.$wrapper;
    if (!wrapper) return;
    wrapper.empty().append(`<div class="text-muted">${__("Loading forecast chart...")}</div>`);
    frappe.call({
        method: "marina_custom_apps.sales_forecasting.api.get_run_preview",
        args: { run_name: frm.doc.name },
        callback(r) {
            const rows = r.message || [];
            wrapper.empty();
            if (!rows.length) {
                wrapper.append(`<div class="text-muted">${__("No forecast results yet.")}</div>`);
                return;
            }
            const labels = rows.map(x => x.date);
            const datasets = [
                { name: __("Forecast"), values: rows.map(x => flt(x.forecast_sales)) }
            ];
            if (rows.every(x => x.actual_sales !== null && x.actual_sales !== undefined)) {
                datasets.push({ name: __("Actual"), values: rows.map(x => flt(x.actual_sales)) });
            }
            new frappe.Chart(wrapper[0], {
                title: __("Daily Sales Forecast"),
                data: { labels, datasets },
                type: "line",
                height: 320,
                axisOptions: { xIsSeries: 1 },
                lineOptions: { hideDots: 1, regionFill: 1 },
                tooltipOptions: { formatTooltipY: d => format_currency(d, "SAR") }
            });
        }
    });
}
