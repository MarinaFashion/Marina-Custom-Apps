frappe.ui.form.on("Stock Entry", {
    setup(frm) {
        frm.marina_transfer_context = null;
        frm.marina_internal_route_update = false;

        marina_install_link_queries(frm);

        frappe.after_ajax(() => {
            marina_install_link_queries(frm);
            marina_bind_link_query_guards(frm);
        });
    },

    async onload(frm) {
        await marina_load_transfer_context(frm);

        if (marina_has_material_request_origin(frm)) {
            await marina_prepare_material_request_stock_entry(frm);
        } else if (frm.is_new()) {
            const allowed = frm.marina_transfer_context?.manual_types || [];
            if (allowed.includes("Send Stock") && !frm.doc.stock_entry_type) {
                await frm.set_value("stock_entry_type", "Send Stock");
            }
            await marina_disable_standard_transit(frm);
        }

        marina_bind_link_query_guards(frm);
        marina_apply_field_controls(frm);
        marina_configure_managed_barcode_scanner(frm);
        marina_install_unexpected_item_button(frm);
    },

    async refresh(frm) {
        marina_install_link_queries(frm);
        marina_bind_link_query_guards(frm);

        frappe.after_ajax(() => {
            marina_install_link_queries(frm);
            marina_bind_link_query_guards(frm);
        });

        await marina_load_transfer_context(frm);

        if (marina_has_material_request_origin(frm)) {
            await marina_prepare_material_request_stock_entry(frm);
        }

        marina_bind_link_query_guards(frm);
        marina_apply_field_controls(frm);
        marina_configure_managed_barcode_scanner(frm);
        marina_install_unexpected_item_button(frm);
        setTimeout(() => {
            marina_force_receive_route_controls(frm);
            marina_force_material_request_route_controls(frm);
        }, 0);

        // ERPNext adds its standard End Transit button during refresh.
        // Replace it after the refresh cycle with Marina's controlled action.
        setTimeout(() => marina_install_end_transit_button(frm), 0);
    },

    async stock_entry_type(frm) {
        if (frm.marina_internal_route_update || !frm.is_new()) {
            marina_bind_link_query_guards(frm);
            marina_apply_field_controls(frm);
            return;
        }

        if (frm.doc.stock_entry_type === "Receive Stock" &&
            !frm.doc.custom_receive_via_end_transit) {
            frappe.msgprint(__("Receive Stock cannot be created manually. Use End Transit."));
            frm.marina_internal_route_update = true;
            await frm.set_value("stock_entry_type", "Send Stock");
            frm.marina_internal_route_update = false;
        }

        await marina_disable_standard_transit(frm);
        await marina_clear_route(frm, true);
        marina_bind_link_query_guards(frm);
        marina_apply_field_controls(frm);
        marina_configure_managed_barcode_scanner(frm);
    },

    async from_warehouse(frm) {
        if (frm.marina_internal_route_update || marina_has_material_request_origin(frm)) return;

        frm.marina_internal_route_update = true;
        try {
            await marina_disable_standard_transit(frm);
            await frm.set_value("to_warehouse", null);
            await frm.set_value("custom_intended_final_warehouse", null);
            await marina_sync_child_route(frm);
        } finally {
            frm.marina_internal_route_update = false;
        }

        marina_bind_link_query_guards(frm);
    },

    async to_warehouse(frm) {
        if (frm.marina_internal_route_update || marina_has_material_request_origin(frm)) return;

        if (frm.doc.stock_entry_type === "Send Stock" && frm.doc.to_warehouse) {
            const result = await frappe.call({
                method: "marina_custom_apps.stock_transfer_control.api.derive_intended_final_warehouse",
                args: { transit_warehouse: frm.doc.to_warehouse },
            });
            await frm.set_value("custom_intended_final_warehouse", result.message || null);
        } else if (frm.doc.stock_entry_type !== "Receive Stock") {
            await frm.set_value("custom_intended_final_warehouse", null);
        }

        await marina_sync_child_route(frm);
        marina_bind_link_query_guards(frm);
    },

    validate(frm) {
        marina_remove_route_only_blank_rows(frm);
        marina_update_transfer_total_qty(frm);

        if (!marina_has_material_request_origin(frm)) {
            marina_sync_child_route(frm);
        }
    },
});

frappe.ui.form.on("Stock Entry Detail", {
    s_warehouse(frm, cdt, cdn) {
        marina_restore_row_route(frm, cdt, cdn);
    },
    t_warehouse(frm, cdt, cdn) {
        marina_restore_row_route(frm, cdt, cdn);
    },
    items_add(frm, cdt, cdn) {
        marina_restore_row_route(frm, cdt, cdn);
        marina_update_transfer_total_qty(frm);
    },
    items_remove(frm) {
        marina_update_transfer_total_qty(frm);
    },
    qty(frm) {
        marina_update_transfer_total_qty(frm);
    },
    custom_actual_received_qty(frm, cdt, cdn) {
        marina_update_receive_discrepancy(frm, cdt, cdn);
    },
});


function marina_source_query(frm) {
    return {
        query: "marina_custom_apps.stock_transfer_control.api.search_source_warehouses",
        filters: {
            stock_entry_type: frm.doc.stock_entry_type || "Send Stock",
        },
    };
}


function marina_target_query(frm) {
    return {
        query: "marina_custom_apps.stock_transfer_control.api.search_target_warehouses",
        filters: {
            stock_entry_type: frm.doc.stock_entry_type || "Send Stock",
            source_warehouse: frm.doc.from_warehouse || "",
        },
    };
}


function marina_install_link_queries(frm) {
    frm.set_query("stock_entry_type", () => {
        const manual_types = frm.marina_transfer_context?.manual_types || ["Send Stock"];
        return {
            filters: [
                ["Stock Entry Type", "name", "in",
                    manual_types.length ? manual_types : ["__none__"]]
            ],
        };
    });

    frm.set_query("from_warehouse", () => marina_source_query(frm));
    frm.set_query("to_warehouse", () => marina_target_query(frm));

    // Also take ownership of the live Link controls.
    marina_force_link_control_queries(frm);
}


function marina_force_link_control_queries(frm) {
    const source = frm.fields_dict.from_warehouse;
    const target = frm.fields_dict.to_warehouse;

    if (source) {
        source.get_query = () => marina_source_query(frm);
    }

    if (target) {
        target.get_query = () => marina_target_query(frm);
    }
}


function marina_bind_link_query_guards(frm) {
    marina_force_link_control_queries(frm);

    const source = frm.fields_dict.from_warehouse;
    const target = frm.fields_dict.to_warehouse;

    if (source?.$input) {
        source.$input
            .off(".marina_stock_transfer_query")
            .on("focus.marina_stock_transfer_query mousedown.marina_stock_transfer_query", () => {
                source.get_query = () => marina_source_query(frm);
            });
    }

    if (target?.$input) {
        target.$input
            .off(".marina_stock_transfer_query")
            .on("focus.marina_stock_transfer_query mousedown.marina_stock_transfer_query", () => {
                target.get_query = () => marina_target_query(frm);
            });
    }
}


function marina_is_managed_send(frm) {
    return frm.doc.stock_entry_type === "Send Stock";
}


async function marina_disable_standard_transit(frm) {
    if (!marina_is_managed_send(frm) || marina_has_material_request_origin(frm)) {
        return;
    }

    if (frm.fields_dict.add_to_transit) {
        frm.set_df_property("add_to_transit", "read_only", 1);
        frm.set_df_property("add_to_transit", "hidden", 1);
    }

    if (frm.doc.add_to_transit) {
        await frm.set_value("add_to_transit", 0);
    }
}


async function marina_load_transfer_context(frm) {
    if (frm.marina_transfer_context) return;

    const result = await frappe.call({
        method: "marina_custom_apps.stock_transfer_control.api.get_transfer_context",
    });
    frm.marina_transfer_context = result.message || {};
}


function marina_has_material_request_origin(frm) {
    return (frm.doc.items || []).some(row => !!row.material_request);
}


function marina_material_request_names(frm) {
    return [...new Set((frm.doc.items || []).map(row => row.material_request).filter(Boolean))];
}


function marina_apply_field_controls(frm) {
    const is_receive = frm.doc.stock_entry_type === "Receive Stock";
    const from_mr = marina_has_material_request_origin(frm);

    frm.set_df_property("stock_entry_type", "read_only", is_receive || from_mr || !frm.is_new());
    frm.set_df_property("from_warehouse", "read_only", is_receive || from_mr);
    frm.set_df_property("to_warehouse", "read_only", is_receive || from_mr);
    frm.set_df_property("custom_intended_final_warehouse", "read_only", 1);
    if (frm.fields_dict.outgoing_stock_entry) {
        frm.set_df_property("outgoing_stock_entry", "hidden", !is_receive);
        frm.set_df_property("outgoing_stock_entry", "read_only", 1);
    }
    frm.set_df_property("custom_receiving_method", "hidden", !is_receive);
    frm.set_df_property("custom_receiving_method", "read_only", 1);

    const is_manual_barcode_receive =
        is_receive &&
        frm.doc.custom_receiving_method === "Manual / Barcode Receiving" &&
        frm.doc.docstatus === 0;

    if (frm.fields_dict.scan_barcode) {
        frm.set_df_property("scan_barcode", "hidden", is_receive && !is_manual_barcode_receive);
        frm.set_df_property("scan_barcode", "read_only", is_receive && !is_manual_barcode_receive);
    }

    marina_force_receive_route_controls(frm);
    marina_force_material_request_route_controls(frm);

    if (frm.fields_dict.custom_unexpected_received_items) {
        frm.set_df_property("custom_unexpected_received_items", "hidden", !is_receive);
        frm.set_df_property("custom_unexpected_received_items", "read_only", 1);
    }

    const is_send_or_between =
        frm.doc.stock_entry_type === "Send Stock" ||
        frm.doc.stock_entry_type === "Transfer Between";
    const show_any_totals = is_receive || is_send_or_between;

    if (frm.fields_dict.custom_transfer_totals_section) {
        frm.set_df_property("custom_transfer_totals_section", "hidden", !show_any_totals);
    }
    if (frm.fields_dict.custom_total_qty) {
        frm.set_df_property("custom_total_qty", "hidden", !is_send_or_between);
        frm.set_df_property("custom_total_qty", "read_only", 1);
    }
    for (const fieldname of [
        "custom_total_sent_qty",
        "custom_total_received_qty",
        "custom_totals_column_break",
        "custom_total_variance_qty",
        "custom_total_abs_variance_qty",
    ]) {
        if (frm.fields_dict[fieldname]) {
            frm.set_df_property(fieldname, "hidden", !is_receive);
            frm.set_df_property(fieldname, "read_only", 1);
        }
    }

    if (is_receive) {
        marina_update_receive_totals(frm);
    } else if (is_send_or_between) {
        marina_update_transfer_total_qty(frm);
    }

    const grid = frm.fields_dict.items?.grid;
    if (grid) {
        // Keep Frappe's normal/user-specific column arrangement.
        // Only enforce business-state properties; do not force order/width.
        grid.update_docfield_property("s_warehouse", "read_only", 1);
        grid.update_docfield_property("t_warehouse", "read_only", 1);

        grid.update_docfield_property("qty", "hidden", 0);
        grid.update_docfield_property(
            "custom_actual_received_qty",
            "hidden",
            is_receive ? 0 : 1
        );
        grid.update_docfield_property(
            "custom_discrepancy_qty",
            "hidden",
            is_receive ? 0 : 1
        );
        grid.update_docfield_property("custom_unexpected_item", "hidden", 1);

        if (is_receive) {
            grid.update_docfield_property("qty", "read_only", 1);
            grid.update_docfield_property(
                "custom_actual_received_qty",
                "read_only",
                frm.doc.docstatus !== 0
            );
            grid.update_docfield_property(
                "custom_discrepancy_qty",
                "read_only",
                1
            );
        }

        grid.refresh();
    }
}


function marina_is_route_only_blank_row(row) {
    return (
        !row.item_code &&
        Number(row.qty || 0) === 0 &&
        !row.material_request &&
        !row.material_request_item &&
        !row.batch_no &&
        !row.serial_no &&
        !row.serial_and_batch_bundle
    );
}


function marina_find_blank_route_row(frm) {
    const source = frm.doc.from_warehouse || "";
    const target = frm.doc.to_warehouse || "";

    const rows = (frm.doc.items || []).filter((row) =>
        marina_is_route_only_blank_row(row) &&
        (row.s_warehouse || "") === source &&
        (row.t_warehouse || "") === target
    );

    return rows.length ? rows[0] : null;
}


function marina_remove_route_only_blank_rows(frm) {
    const removable = (frm.doc.items || []).filter(marina_is_route_only_blank_row);
    if (!removable.length) return;

    for (const row of removable) {
        if (locals[row.doctype]?.[row.name]) {
            delete locals[row.doctype][row.name];
        }
    }

    frm.doc.items = (frm.doc.items || []).filter(
        (row) => !marina_is_route_only_blank_row(row)
    );
    frm.doc.items.forEach((row, index) => {
        row.idx = index + 1;
    });
    frm.refresh_field("items");
}


function marina_update_transfer_total_qty(frm) {
    const managed =
        frm.doc.stock_entry_type === "Send Stock" ||
        frm.doc.stock_entry_type === "Transfer Between";

    if (!managed || !frm.fields_dict.custom_total_qty) return;

    const total = (frm.doc.items || []).reduce(
        (sum, row) => sum + (row.item_code ? Number(row.qty || 0) : 0),
        0
    );

    if (Number(frm.doc.custom_total_qty || 0) !== total) {
        frm.set_value("custom_total_qty", total);
    }
}

function marina_find_existing_scan_row(frm, item_code, barcode, uom) {
    const source = frm.doc.from_warehouse || "";
    const target = frm.doc.to_warehouse || "";

    const candidates = (frm.doc.items || []).filter((row) => {
        if (row.item_code !== item_code) return false;
        if ((row.s_warehouse || "") !== source) return false;
        if ((row.t_warehouse || "") !== target) return false;
        if (uom && row.uom && row.uom !== uom) return false;
        return true;
    });

    if (barcode) {
        const exact = candidates.filter((row) => (row.barcode || "") === barcode);
        if (exact.length) return exact[0];

        const without_barcode = candidates.filter((row) => !row.barcode);
        if (without_barcode.length === 1) return without_barcode[0];
        return null;
    }

    return candidates.length === 1 ? candidates[0] : null;
}


function marina_item_is_expected_on_receive(frm, item_code) {
    return (frm.doc.items || []).some((row) => row.item_code === item_code);
}


async function marina_add_unexpected_receive_item(frm, values) {
    const item_code = values.item_code;
    const barcode = (values.barcode || "").trim();
    const actual_qty = Number(values.actual_received_qty || 0);

    if (!item_code) frappe.throw(__("Item Code is required."));
    if (!(actual_qty > 0)) frappe.throw(__("Actual Received Qty must be greater than zero."));

    if (marina_item_is_expected_on_receive(frm, item_code)) {
        frappe.throw(
            __("Item {0} exists on the original Send Stock. Update its Actual Received Qty in the Items table instead.", [item_code])
        );
    }

    let row = marina_find_unexpected_receive_row(frm, item_code, barcode);
    if (row) {
        const next_actual = Number(row.actual_received_qty || 0) + actual_qty;
        await frappe.model.set_value(row.doctype, row.name, {
            actual_received_qty: next_actual,
            discrepancy_qty: -next_actual,
            source_warehouse: frm.doc.from_warehouse,
            target_warehouse: frm.doc.to_warehouse,
        });
    } else {
        frm.add_child("custom_unexpected_received_items", {
            barcode,
            item_code,
            actual_received_qty: actual_qty,
            discrepancy_qty: -actual_qty,
            source_warehouse: frm.doc.from_warehouse,
            target_warehouse: frm.doc.to_warehouse,
        });
        frm.refresh_field("custom_unexpected_received_items");
    }

    marina_update_receive_totals(frm);
    frm.dirty();
}


function marina_install_unexpected_item_button(frm) {
    frm.remove_custom_button(__("Add Unexpected Item"), __("Receiving"));

    const allowed =
        frm.doc.stock_entry_type === "Receive Stock" &&
        frm.doc.docstatus === 0 &&
        !!frm.doc.custom_receive_via_end_transit;

    if (!allowed) return;

    frm.add_custom_button(
        __("Add Unexpected Item"),
        () => {
            const dialog = new frappe.ui.Dialog({
                title: __("Add Unexpected Received Item"),
                fields: [
                    {
                        fieldname: "item_code",
                        fieldtype: "Link",
                        label: __("Item Code"),
                        options: "Item",
                        reqd: 1,
                        get_query: () => ({
                            filters: {disabled: 0, is_stock_item: 1},
                        }),
                    },
                    {
                        fieldname: "barcode",
                        fieldtype: "Data",
                        label: __("Barcode"),
                        description: __("Optional."),
                    },
                    {
                        fieldname: "actual_received_qty",
                        fieldtype: "Float",
                        label: __("Actual Received Qty"),
                        reqd: 1,
                        default: 1,
                    },
                ],
                primary_action_label: __("Add"),
                primary_action: async (values) => {
                    try {
                        await marina_add_unexpected_receive_item(frm, values);
                        dialog.hide();
                        frappe.show_alert({
                            message: __("Unexpected item recorded for audit."),
                            indicator: "orange",
                        });
                    } catch (error) {}
                },
            });
            dialog.show();
        },
        __("Receiving")
    );
}

function marina_find_unexpected_receive_row(frm, item_code, barcode) {
    return (frm.doc.custom_unexpected_received_items || []).find((row) =>
        row.item_code === item_code && (row.barcode || "") === (barcode || "")
    );
}


async function marina_increment_expected_receive_row(frm, row) {
    const next_actual = Number(row.custom_actual_received_qty || 0) + 1;
    await frappe.model.set_value(
        row.doctype,
        row.name,
        "custom_actual_received_qty",
        next_actual
    );
    marina_update_receive_totals(frm);
}


async function marina_increment_unexpected_receive_row(frm, data) {
    await marina_add_unexpected_receive_item(frm, {
        item_code: data.item_code,
        barcode: data.barcode || "",
        actual_received_qty: 1,
    });
}


function marina_process_manual_receive_scan(frm, scanner) {
    return new Promise((resolve, reject) => {
        const input = scanner.scan_barcode_field.value;
        scanner.scan_barcode_field.set_value("");
        if (!input) {
            resolve();
            return;
        }

        scanner.scan_api_call(input, async (r) => {
            const data = r && r.message;
            if (!data || !data.item_code) {
                scanner.show_alert(__("Cannot find Item with this Barcode"), "red");
                scanner.play_fail_sound();
                reject();
                return;
            }

            try {
                const expected = marina_find_existing_scan_row(
                    frm,
                    data.item_code,
                    data.barcode,
                    data.uom
                );

                if (expected) {
                    await marina_increment_expected_receive_row(frm, expected);
                    scanner.show_alert(
                        __("Received {0}: Actual Received Qty increased.", [data.item_code]),
                        "green"
                    );
                } else {
                    await marina_increment_unexpected_receive_row(frm, data);
                    scanner.show_alert(
                        __("Unexpected item {0} recorded for audit.", [data.item_code]),
                        "orange"
                    );
                }

                scanner.play_success_sound();
                resolve();
            } catch (error) {
                scanner.play_fail_sound();
                reject(error);
            }
        });
    });
}

function marina_configure_managed_barcode_scanner(frm) {
    const is_send = frm.doc.stock_entry_type === "Send Stock" && frm.doc.docstatus === 0;
    const is_transfer_between =
        frm.doc.stock_entry_type === "Transfer Between" && frm.doc.docstatus === 0;
    const is_manual_receive =
        frm.doc.stock_entry_type === "Receive Stock" &&
        frm.doc.custom_receiving_method === "Manual / Barcode Receiving" &&
        frm.doc.docstatus === 0;

    if (!(is_send || is_transfer_between || is_manual_receive)) return;

    if (!frm.cscript || !erpnext?.utils?.BarcodeScanner) {
        console.warn("Marina barcode control: ERPNext BarcodeScanner unavailable.");
        return;
    }

    const scanner = new erpnext.utils.BarcodeScanner({
        frm,
        qty_field: is_manual_receive ? "custom_actual_received_qty" : "qty",
        barcode_field: "barcode",
        items_table_name: "items",
        dont_allow_new_row: false,
        warehouse_field: () => "s_warehouse",
    });

    if (is_manual_receive) {
        // Receive scans never create rows in standard Stock Entry Items.
        // Expected items increment Actual Received Qty. Unexpected items are
        // stored in the audit-only child table below Items.
        scanner.process_scan = () => marina_process_manual_receive_scan(frm, scanner);
        frm.cscript.barcode_scanner = scanner;
        return;
    }

    // Send / Transfer Between keep deterministic same-row Qty increments.
    const standard_get_row = scanner.get_row_to_modify_on_scan.bind(scanner);
    scanner.get_row_to_modify_on_scan = function (
        item_code,
        batch_no,
        uom,
        barcode,
        default_warehouse
    ) {
        if (batch_no) {
            return standard_get_row(
                item_code,
                batch_no,
                uom,
                barcode,
                default_warehouse
            );
        }

        const existing = marina_find_existing_scan_row(
            frm,
            item_code,
            barcode,
            uom
        );
        if (existing) return existing;

        const blank_route_row = marina_find_blank_route_row(frm);
        if (blank_route_row) return blank_route_row;

        return null;
    };

    frm.cscript.barcode_scanner = scanner;
}

function marina_force_material_request_route_controls(frm) {
    if (!marina_has_material_request_origin(frm)) return;

    for (const fieldname of ["from_warehouse", "to_warehouse"]) {
        const control = frm.fields_dict[fieldname];
        frm.set_df_property(fieldname, "read_only", 1);

        if (!control) continue;
        control.df.read_only = 1;
        control.refresh();

        if (control.$input) {
            control.$input.prop("readonly", true).prop("disabled", true);
        }
    }
}

function marina_force_receive_route_controls(frm) {
    if (frm.doc.stock_entry_type !== "Receive Stock") return;

    const source = frm.fields_dict.from_warehouse;
    const target = frm.fields_dict.to_warehouse;

    frm.set_df_property("from_warehouse", "read_only", 1);
    frm.set_df_property("to_warehouse", "read_only", 1);

    for (const control of [source, target]) {
        if (!control) continue;
        control.df.read_only = 1;
        control.refresh();
        if (control.$input) {
            control.$input.prop("readonly", true).prop("disabled", true);
        }
    }
}


async function marina_clear_route(frm, clear_source) {
    frm.marina_internal_route_update = true;

    try {
        if (clear_source) await frm.set_value("from_warehouse", null);
        await frm.set_value("to_warehouse", null);
        await frm.set_value("custom_intended_final_warehouse", null);

        for (const row of (frm.doc.items || [])) {
            await frappe.model.set_value(row.doctype, row.name, "s_warehouse", null);
            await frappe.model.set_value(row.doctype, row.name, "t_warehouse", null);
        }
    } finally {
        frm.marina_internal_route_update = false;
    }
}


async function marina_sync_child_route(frm) {
    const source = frm.doc.from_warehouse || null;
    const target = frm.doc.to_warehouse || null;

    for (const row of (frm.doc.items || [])) {
        if (row.s_warehouse !== source) {
            await frappe.model.set_value(row.doctype, row.name, "s_warehouse", source);
        }
        if (row.t_warehouse !== target) {
            await frappe.model.set_value(row.doctype, row.name, "t_warehouse", target);
        }
    }

    frm.refresh_field("items");
}


function marina_update_receive_discrepancy(frm, cdt, cdn) {
    if (frm.doc.stock_entry_type !== "Receive Stock") return;

    const row = locals[cdt][cdn];
    if (!row) return;

    const sent = Number(row.qty || 0);
    const actual = Number(row.custom_actual_received_qty || 0);

    if (actual < 0) {
        frappe.model.set_value(cdt, cdn, "custom_actual_received_qty", 0);
        frappe.msgprint(__("Actual Received Qty cannot be negative."));
        return;
    }

    frappe.model.set_value(cdt, cdn, "custom_discrepancy_qty", sent - actual).then(() => marina_update_receive_totals(frm));
}


function marina_update_receive_totals(frm) {
    if (frm.doc.stock_entry_type !== "Receive Stock") return;

    const rows = frm.doc.items || [];
    const total_sent = rows.reduce((sum, row) => sum + Number(row.qty || 0), 0);
    const expected_received = rows.reduce(
        (sum, row) => sum + Number(row.custom_actual_received_qty || 0),
        0
    );
    const unexpected_rows = frm.doc.custom_unexpected_received_items || [];
    const unexpected_received = unexpected_rows.reduce(
        (sum, row) => sum + Number(row.actual_received_qty || 0),
        0
    );
    const total_received = expected_received + unexpected_received;
    const total_variance = total_sent - total_received;
    const expected_abs_variance = rows.reduce(
        (sum, row) =>
            sum + Math.abs(
                Number(row.qty || 0) -
                Number(row.custom_actual_received_qty || 0)
            ),
        0
    );
    const unexpected_abs_variance = unexpected_rows.reduce(
        (sum, row) => sum + Math.abs(Number(row.actual_received_qty || 0)),
        0
    );
    const total_abs_variance = expected_abs_variance + unexpected_abs_variance;

    const values = {
        custom_total_sent_qty: total_sent,
        custom_total_received_qty: total_received,
        custom_total_variance_qty: total_variance,
        custom_total_abs_variance_qty: total_abs_variance,
    };

    for (const [fieldname, value] of Object.entries(values)) {
        if (frm.fields_dict[fieldname] && frm.doc[fieldname] !== value) {
            frm.set_value(fieldname, value);
        }
    }
}


function marina_restore_row_route(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;

    const source = frm.doc.from_warehouse || null;
    const target = frm.doc.to_warehouse || null;

    if (row.s_warehouse !== source) {
        frappe.model.set_value(cdt, cdn, "s_warehouse", source);
    }

    if (row.t_warehouse !== target) {
        frappe.model.set_value(cdt, cdn, "t_warehouse", target);
    }
}


async function marina_prepare_material_request_stock_entry(frm) {
    if (!frm.is_new()) return;

    const material_requests = marina_material_request_names(frm);
    if (!material_requests.length) return;

    const result = await frappe.call({
        method: "marina_custom_apps.stock_transfer_control.api.get_material_request_stock_entry_route",
        args: { material_requests },
    });

    const route = result.message || {};
    if (!route.from_warehouse || !route.to_warehouse) {
        frappe.throw(__("Could not resolve the Material Request warehouse route."));
    }

    frm.marina_internal_route_update = true;

    try {
        await frm.set_value("stock_entry_type", route.stock_entry_type || "Send Stock");
        await frm.set_value("from_warehouse", route.from_warehouse);
        await frm.set_value("to_warehouse", route.to_warehouse);
        await frm.set_value(
            "custom_intended_final_warehouse",
            route.intended_final_warehouse || null
        );

        if (frm.fields_dict.custom_dc_dispatch_run && route.dc_dispatch_run) {
            await frm.set_value("custom_dc_dispatch_run", route.dc_dispatch_run);
        }

        if (frm.fields_dict.custom_final_store_warehouse && route.final_store_warehouse) {
            await frm.set_value(
                "custom_final_store_warehouse",
                route.final_store_warehouse
            );
        }

        if (frm.fields_dict.custom_dc_dispatch_instructions &&
            route.dc_dispatch_instructions) {
            await frm.set_value(
                "custom_dc_dispatch_instructions",
                route.dc_dispatch_instructions
            );
        }

        await marina_sync_child_route(frm);
    } finally {
        frm.marina_internal_route_update = false;
    }

    marina_bind_link_query_guards(frm);
    marina_apply_field_controls(frm);
}


function marina_open_receive_stock_clean(receive_name) {
    if (!receive_name) {
        frappe.throw(__("Receive Stock name is required."));
    }

    // End Transit switches from a Send Stock to a Receive Stock. A normal
    // Desk route change can reuse the current Stock Entry form/grid instance,
    // leaving child-field dependency metadata in the previous Send state.
    // Open the Receive document through a full browser navigation so Frappe
    // initializes the form and child grid from the Receive Stock parent state.
    const path = `/app/stock-entry/${encodeURIComponent(receive_name)}`;
    window.location.assign(path);
}

function marina_is_submitted_send_waiting_for_receipt(frm) {
    return (
        frm.doc.docstatus === 1 &&
        frm.doc.stock_entry_type === "Send Stock" &&
        !!frm.doc.add_to_transit &&
        Number(frm.doc.per_transferred || 0) < 100
    );
}


function marina_install_end_transit_button(frm) {
    // Remove ERPNext's standard End Transit action. Marina Receive Stock must
    // always be created through the controlled server method below.
    frm.remove_custom_button(__("End Transit"));

    if (!marina_is_submitted_send_waiting_for_receipt(frm)) {
        return;
    }

    frm.add_custom_button(__("End Transit"), async () => {
        const status_result = await frappe.call({
            method: "marina_custom_apps.stock_transfer_control.end_transit.get_receive_status",
            args: { send_stock: frm.doc.name },
        });
        const status = status_result.message || {};

        if (status.exists && status.receiving_method) {
            marina_open_receive_stock_clean(status.name);
            return;
        }

        frappe.prompt(
            [
                {
                    fieldname: "receiving_method",
                    fieldtype: "Select",
                    label: __("Receiving Method"),
                    options: [
                        "",
                        "Normal Receiving",
                        "Manual / Barcode Receiving",
                    ].join("\n"),
                    reqd: 1,
                    description: __(
                        "This choice is saved once and cannot be changed on this Receive Stock."
                    ),
                },
            ],
            async (values) => {
                const result = await frappe.call({
                    method: "marina_custom_apps.stock_transfer_control.end_transit.create_or_open_receive_stock",
                    args: {
                        send_stock: frm.doc.name,
                        receiving_method: values.receiving_method,
                    },
                    freeze: true,
                    freeze_message: __("Preparing controlled Receive Stock..."),
                });

                const receive = result.message || {};
                if (!receive.name) {
                    frappe.throw(__("Receive Stock could not be created."));
                }

                frappe.show_alert({
                    message: receive.created
                        ? __("Receive Stock {0} created.", [receive.name])
                        : __("Opening existing Receive Stock {0}.", [receive.name]),
                    indicator: receive.created ? "green" : "blue",
                });

                marina_open_receive_stock_clean(receive.name);
            },
            __("Choose Receiving Method"),
            __("Continue")
        );
    });
}
