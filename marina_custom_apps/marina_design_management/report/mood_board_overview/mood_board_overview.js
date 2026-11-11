frappe.query_reports["Mood Board Overview"] = {
    filters: [
        {fieldname: "year", label: __("Year"), fieldtype: "Data", on_change: marina_overview_filters_changed},
        {fieldname: "season", label: __("Season"), fieldtype: "Select",
            options: "\nRamadan\nSummer\nWinter", on_change: marina_overview_filters_changed},
        {fieldname: "collection", label: __("Collection"), fieldtype: "Select",
            options: "\nEID\nRamadan\nHajj\nSummer\nAutumn\nWinter",
            on_change: marina_overview_filters_changed},
        {fieldname: "drop", label: __("Drop"), fieldtype: "Select",
            options: "\nDrop- 01\nDrop- 02\nDrop- 03\nDrop- 04\nDrop- B2S\nDrop- Reorder\nNot Assigned",
            on_change: marina_overview_filters_changed},
        {fieldname: "mood_boards", label: __("Mood Board"), fieldtype: "MultiSelectList",
            on_change: marina_overview_filters_changed,
            get_data(txt) {
                const report = frappe.query_report;
                const filters = {};
                ["year", "season", "collection", "drop"].forEach(key => {
                    const value = report.get_filter_value(key);
                    if (value) filters[key] = value;
                });
                return frappe.db.get_link_options("Mood Board", txt, filters);
            }}
    ],
    onload(report) {
        report.page.set_primary_action(__("Run Report"), () => report.refresh());
        report.page.add_inner_button(__("Print / Save as PDF"), () => marina_overview_print(report));
        // QueryReport is shared across routes: delegate other reports to native printing.
        if (!report._marina_overview_print_installed) {
            ["print_report", "pdf_report"].forEach(method => {
                const original = report[method];
                report[method] = function (...args) {
                    if (this.report_name === "Mood Board Overview") return marina_overview_print(this);
                    return original.apply(this, args);
                };
            });
            report._marina_overview_print_installed = true;
        }
    },
    after_datatable_render(datatable) {
        const report = frappe.query_report;
        if (report.report_name !== "Mood Board Overview") return;
        report.$report.find(".datatable").hide();
        // The standard footer is added immediately after rendering the table.
        requestAnimationFrame(() => {
            if (report.report_name === "Mood Board Overview") report.$report_footer?.hide();
        });
    }
};

function marina_overview_filters_changed(report) {
    if (report._no_refresh) return;
    report.last_ajax?.abort();
    report.$status.empty().hide();
    report.toggle_report(false);
    report.$report_footer?.hide();
    report.data = [];
    report.toggle_message(true, __("Filters changed. Click Run Report to update the overview."));
}

function marina_overview_print(report) {
    const frame = report.$status.find("iframe.marina-mood-board-preview")[0];
    if (!frame) {
        frappe.msgprint(__("Run the report before printing."));
        return;
    }
    const doc = frame.contentDocument;
    if (!doc || doc.readyState !== "complete" || Array.from(doc.images).some(img => !img.complete)) {
        frappe.msgprint(__("Please wait for the report images to finish loading."));
        return;
    }
    frame.contentWindow.focus();
    frame.contentWindow.print();
}
