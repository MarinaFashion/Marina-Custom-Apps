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
        setTimeout(() => marina_force_receive_route_controls(frm), 0);

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

    marina_force_receive_route_controls(frm);

    const grid = frm.fields_dict.items?.grid;
    if (grid) {
        grid.update_docfield_property("s_warehouse", "read_only", 1);
        grid.update_docfield_property("t_warehouse", "read_only", 1);
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
            frappe.set_route("Form", "Stock Entry", status.name);
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

                frappe.set_route("Form", "Stock Entry", receive.name);
            },
            __("Choose Receiving Method"),
            __("Continue")
        );
    });
}
