frappe.ui.form.on("Forecast Buying Plan", {
    refresh(frm) {
        render_plan_indicators(frm);

        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Paste from Excel"), () => open_paste_dialog(frm), __("Buying Plan"));
            frm.add_custom_button(__("Refresh ERP Progress"), () => refresh_progress(frm), __("Buying Plan"));
        }

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Refresh ERP Progress"), () => refresh_progress(frm), __("Buying Plan"));
            frm.add_custom_button(__("Create Revision"), () => create_revision(frm), __("Buying Plan"));
        }
    },

    validate(frm) {
        calculate_all_rows(frm);
    }
});

frappe.ui.form.on("Forecast Buying Plan Item", {
    planned_styles: calculate_child,
    planned_total_qty: calculate_child,
    planned_total_cost: calculate_child,
    planned_selling_value: calculate_child,
    items_remove(frm) { calculate_parent_totals(frm); }
});

function calculate_child(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    frappe.db.get_single_value("Sales Forecast Settings", "vat_rate").then(vat => {
        calculate_row(row, flt(vat || 15));
        frm.refresh_field("items");
        calculate_parent_totals(frm);
    });
}

function calculate_all_rows(frm) {
    const vat = 15;
    (frm.doc.items || []).forEach(row => calculate_row(row, vat));
    calculate_parent_totals(frm);
}

function calculate_row(row, vat_rate) {
    const styles = flt(row.planned_styles);
    const qty = flt(row.planned_total_qty);
    const cost = flt(row.planned_total_cost);
    const selling = flt(row.planned_selling_value);
    const ex_vat = selling / (1 + flt(vat_rate) / 100);
    const profit = ex_vat - cost;

    row.avg_qty_per_style = styles ? qty / styles : 0;
    row.avg_cost_per_unit = qty ? cost / qty : 0;
    row.planned_asp = qty ? selling / qty : 0;
    row.selling_value_ex_vat = ex_vat;
    row.planned_gross_profit = profit;
    row.planned_margin_pct = ex_vat ? profit / ex_vat * 100 : 0;
}

function calculate_parent_totals(frm) {
    const rows = frm.doc.items || [];
    const sum = (field) => rows.reduce((a, r) => a + flt(r[field]), 0);
    const selling_ex = sum("selling_value_ex_vat");
    const profit = sum("planned_gross_profit");

    frm.set_value("total_styles", sum("planned_styles"));
    frm.set_value("total_qty", sum("planned_total_qty"));
    frm.set_value("total_cost", sum("planned_total_cost"));
    frm.set_value("total_selling_value", sum("planned_selling_value"));
    frm.set_value("selling_value_ex_vat", selling_ex);
    frm.set_value("planned_gross_profit", profit);
    frm.set_value("planned_margin_pct", selling_ex ? profit / selling_ex * 100 : 0);
}

function render_plan_indicators(frm) {
    if (!frm.doc.total_qty) return;
    frm.dashboard.add_indicator(__("Plan Qty: {0}", [format_number(frm.doc.total_qty)]), "blue");
    frm.dashboard.add_indicator(__("Styles: {0}", [frm.doc.total_styles || 0]), "blue");
    frm.dashboard.add_indicator(__("Margin: {0}%", [flt(frm.doc.planned_margin_pct).toFixed(1)]), flt(frm.doc.planned_margin_pct) >= 70 ? "green" : "orange");
    if (frm.doc.styles_created || frm.doc.po_qty || frm.doc.received_qty) {
        frm.dashboard.add_indicator(__("Assortment: {0}%", [flt(frm.doc.assortment_readiness_pct).toFixed(0)]), "purple");
        frm.dashboard.add_indicator(__("PO: {0}%", [flt(frm.doc.po_completion_pct).toFixed(0)]), "orange");
        frm.dashboard.add_indicator(__("Received: {0}%", [flt(frm.doc.receipt_completion_pct).toFixed(0)]), "green");
    }
}

function open_paste_dialog(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __("Paste Marina Buying Plan"),
        size: "extra-large",
        fields: [
            {
                fieldname: "instructions",
                fieldtype: "HTML",
                options: `<div class="alert alert-info mb-3">
                    <b>${__("Copy the rows directly from Excel, including or excluding the header.")}</b><br>
                    ${__("Expected order: Year, Season, Collection, Drop, Display Date, Group, Styles, Avg Qty, Total Qty, Avg Cost, Total Cost, Total Selling Value")}
                </div>`
            },
            { fieldname: "data", fieldtype: "Long Text", label: __("Excel Rows"), reqd: 1 }
        ],
        primary_action_label: __("Import Plan"),
        primary_action(values) {
            try {
                const parsed = parse_excel_plan(values.data);
                if (!parsed.length) throw new Error(__("No valid rows found."));

                frm.clear_table("items");
                frm.set_value("plan_year", parsed[0].year);
                frm.set_value("season", parsed[0].season);

                parsed.forEach(r => {
                    const row = frm.add_child("items");
                    row.collection = r.collection;
                    row.drop = r.drop;
                    row.display_date = r.display_date;
                    row.main_group = r.group;
                    row.planned_styles = r.styles;
                    row.planned_total_qty = r.total_qty;
                    row.planned_total_cost = r.total_cost;
                    row.planned_selling_value = r.total_selling_value;
                    calculate_row(row, 15);
                });

                frm.refresh_field("items");
                calculate_parent_totals(frm);
                dialog.hide();
                frappe.show_alert({ message: __("{0} buying-plan rows imported", [parsed.length]), indicator: "green" });
            } catch (e) {
                frappe.msgprint({ title: __("Unable to Import"), message: e.message, indicator: "red" });
            }
        }
    });
    dialog.show();
}

function parse_excel_plan(text) {
    const lines = (text || "").trim().split(/\r?\n/).filter(Boolean);
    if (!lines.length) return [];

    const split = line => line.split("\t").map(v => v.trim());
    let rows = lines.map(split);
    if ((rows[0][0] || "").toLowerCase() === "year") rows = rows.slice(1);

    return rows.filter(r => r.length >= 12).map(r => ({
        year: cint(clean_number(r[0])),
        season: r[1],
        collection: r[2],
        drop: r[3],
        display_date: parse_plan_date(r[4]),
        group: r[5],
        styles: cint(clean_number(r[6])),
        total_qty: flt(clean_number(r[8])),
        total_cost: flt(clean_number(r[10])),
        total_selling_value: flt(clean_number(r[11]))
    }));
}

function clean_number(value) {
    return String(value || "0").replace(/,/g, "").replace(/\s/g, "");
}

function parse_plan_date(value) {
    const v = String(value || "").trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
    const m = v.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (!m) throw new Error(__("Invalid display date: {0}", [v]));
    const [, d, mon, y] = m;
    return `${y}-${String(mon).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function refresh_progress(frm) {
    if (frm.is_new()) {
        frappe.msgprint(__("Save the buying plan before refreshing ERP progress."));
        return;
    }
    frappe.call({
        method: "marina_custom_apps.sales_forecasting.api.refresh_buying_plan_progress",
        args: { plan_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Matching Items, Purchase Orders and Receipts…"),
        callback() {
            frm.reload_doc();
            frappe.show_alert({ message: __("Buying readiness refreshed"), indicator: "green" });
        }
    });
}

function create_revision(frm) {
    frappe.call({
        method: "marina_custom_apps.sales_forecasting.api.create_buying_plan_revision",
        args: { plan_name: frm.doc.name },
        freeze: true,
        callback(r) {
            if (r.message) frappe.set_route("Form", "Forecast Buying Plan", r.message);
        }
    });
}
