frappe.listview_settings["Sales Forecast Daily"] = {
    onload(listview) {
        if (!frappe.user.has_role("System Manager")) return;

        listview.page.add_menu_item(__("Data Mart Maintenance"), async () => {
            let groups = [];
            try {
                const settings = await frappe.db.get_doc("Sales Forecast Settings");
                groups = String(settings.main_groups || "")
                    .split(",")
                    .map(value => value.trim())
                    .filter(Boolean);
            } catch (e) {
                groups = ["Dresses", "Uppers", "Bottoms"];
            }

            const dialog = new frappe.ui.Dialog({
                title: __("Data Mart Maintenance"),
                fields: [
                    { fieldname: "from_date", fieldtype: "Date", label: __("From Date"), reqd: 1 },
                    { fieldname: "to_date", fieldtype: "Date", label: __("To Date"), reqd: 1 },
                    { fieldname: "scope_section", fieldtype: "Section Break", label: __("Optional Scope") },
                    { fieldname: "branch", fieldtype: "Link", options: "Branch", label: __("Branch") },
                    { fieldname: "scope_column", fieldtype: "Column Break" },
                    { fieldname: "main_group", fieldtype: "Select", options: ["", ...groups].join("\n"), label: __("Main Group") },
                    {
                        fieldname: "action",
                        fieldtype: "Select",
                        label: __("Action"),
                        options: "Delete Only\nDelete & Rebuild",
                        default: "Delete Only",
                        reqd: 1
                    },
                    {
                        fieldname: "warning",
                        fieldtype: "HTML",
                        options: '<div class="alert alert-warning">' +
                            __("Existing Data Mart rows are never changed by normal Forecast Runs. Use this only when corrected source data must be picked up.") +
                            "</div>"
                    }
                ],
                primary_action_label: __("Continue"),
                primary_action(values) {
                    if (!values) return;
                    const action = values.action === "Delete & Rebuild" ? "rebuild" : "delete";
                    frappe.call({
                        method: "marina_custom_apps.sales_forecasting.api.get_data_mart_range_count",
                        args: {
                            start_date: values.from_date,
                            end_date: values.to_date,
                            branch: values.branch || null,
                            main_group: values.main_group || null
                        },
                        callback(r) {
                            if (r.exc) return;
                            const count = cint((r.message || {}).count);
                            if (!count) {
                                frappe.msgprint(__("No Data Mart records match this range and scope."));
                                return;
                            }
                            const actionLabel = action === "rebuild" ? __("delete and rebuild") : __("delete");
                            frappe.confirm(
                                __("This will {0} {1} Sales Forecast Daily records. Continue?", [actionLabel, count]),
                                () => {
                                    dialog.hide();
                                    frappe.call({
                                        method: "marina_custom_apps.sales_forecasting.api.queue_data_mart_maintenance",
                                        args: {
                                            start_date: values.from_date,
                                            end_date: values.to_date,
                                            action,
                                            branch: values.branch || null,
                                            main_group: values.main_group || null
                                        },
                                        freeze: true,
                                        freeze_message: __("Queueing Data Mart maintenance..."),
                                        callback(resp) {
                                            if (!resp.exc) {
                                                frappe.show_alert({
                                                    message: __("Data Mart maintenance queued in the long worker."),
                                                    indicator: "orange"
                                                });
                                            }
                                        }
                                    });
                                }
                            );
                        }
                    });
                }
            });
            dialog.show();
        });
    }
};
