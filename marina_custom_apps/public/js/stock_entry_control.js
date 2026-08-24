frappe.ui.form.on("Stock Entry", {
    async setup(frm) {
        frm.marina_transfer_context = null;
        frm.marina_internal_route_update = false;
        await marina_load_transfer_context(frm);
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
        }

        marina_apply_field_controls(frm);
        await marina_configure_queries(frm);
    },

    async refresh(frm) {
        await marina_load_transfer_context(frm);

        if (marina_has_material_request_origin(frm)) {
            await marina_prepare_material_request_stock_entry(frm);
        }

        marina_apply_field_controls(frm);
        await marina_configure_queries(frm);
    },

    async stock_entry_type(frm) {
        if (frm.marina_internal_route_update || !frm.is_new()) {
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

        await marina_clear_route(frm, true);
        marina_apply_field_controls(frm);
        await marina_configure_queries(frm);
    },

    async from_warehouse(frm) {
        if (frm.marina_internal_route_update || marina_has_material_request_origin(frm)) return;

        frm.marina_internal_route_update = true;
        await frm.set_value("to_warehouse", null);
        await frm.set_value("custom_intended_final_warehouse", null);
        await marina_sync_child_route(frm);
        frm.marina_internal_route_update = false;

        await marina_configure_queries(frm);
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
    frm.set_df_property("custom_original_send_stock", "read_only", 1);
    frm.set_df_property("custom_receiving_method", "read_only", 1);

    const grid = frm.fields_dict.items?.grid;
    if (grid) {
        grid.update_docfield_property("s_warehouse", "read_only", 1);
        grid.update_docfield_property("t_warehouse", "read_only", 1);
    }
}

async function marina_configure_queries(frm) {
    if (!frm.is_new() || frm.doc.stock_entry_type === "Receive Stock") return;

    const type = frm.doc.stock_entry_type;
    const manual_types = frm.marina_transfer_context?.manual_types || [];

    frm.set_query("stock_entry_type", () => ({
        filters: [["Stock Entry Type", "name", "in", manual_types.length ? manual_types : ["__none__"]]],
    }));

    if (marina_has_material_request_origin(frm)) return;
    if (!["Send Stock", "Transfer Between"].includes(type)) return;

    const sources = await frappe.call({
        method: "marina_custom_apps.stock_transfer_control.api.get_valid_sources",
        args: { stock_entry_type: type },
    });
    const source_names = sources.message || [];
    frm.set_query("from_warehouse", () => ({
        filters: [["Warehouse", "name", "in", source_names.length ? source_names : ["__none__"]]],
    }));

    if (!frm.doc.from_warehouse) {
        frm.set_query("to_warehouse", () => ({
            filters: [["Warehouse", "name", "in", ["__none__"]]],
        }));
        return;
    }

    const targets = await frappe.call({
        method: "marina_custom_apps.stock_transfer_control.api.get_valid_targets",
        args: {
            stock_entry_type: type,
            source_warehouse: frm.doc.from_warehouse,
        },
    });
    const target_names = targets.message || [];
    frm.set_query("to_warehouse", () => ({
        filters: [["Warehouse", "name", "in", target_names.length ? target_names : ["__none__"]]],
    }));
}

async function marina_clear_route(frm, clear_source) {
    frm.marina_internal_route_update = true;
    if (clear_source) await frm.set_value("from_warehouse", null);
    await frm.set_value("to_warehouse", null);
    await frm.set_value("custom_intended_final_warehouse", null);

    for (const row of (frm.doc.items || [])) {
        await frappe.model.set_value(row.doctype, row.name, "s_warehouse", null);
        await frappe.model.set_value(row.doctype, row.name, "t_warehouse", null);
    }
    frm.marina_internal_route_update = false;
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

    if (row.s_warehouse !== source) frappe.model.set_value(cdt, cdn, "s_warehouse", source);
    if (row.t_warehouse !== target) frappe.model.set_value(cdt, cdn, "t_warehouse", target);
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
        await frm.set_value("custom_intended_final_warehouse", route.intended_final_warehouse || null);

        if (frm.fields_dict.custom_dc_dispatch_run && route.dc_dispatch_run) {
            await frm.set_value("custom_dc_dispatch_run", route.dc_dispatch_run);
        }
        if (frm.fields_dict.custom_final_store_warehouse && route.final_store_warehouse) {
            await frm.set_value("custom_final_store_warehouse", route.final_store_warehouse);
        }
        if (frm.fields_dict.custom_dc_dispatch_instructions && route.dc_dispatch_instructions) {
            await frm.set_value("custom_dc_dispatch_instructions", route.dc_dispatch_instructions);
        }

        await marina_sync_child_route(frm);
    } finally {
        frm.marina_internal_route_update = false;
    }

    marina_apply_field_controls(frm);
}
