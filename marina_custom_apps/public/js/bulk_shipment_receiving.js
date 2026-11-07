/* Marina Bulk Shipment Receiving - draft-only Purchase Receipt helper.
 * Quantities pasted from Excel are in the Item's Stock UOM.
 */
(() => {
    const API = "marina_custom_apps.purchasing.bulk_shipment_receiving";
    const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
    const msg = (text) => frappe.msgprint({title: __("Bulk Shipment Receiving"), message: text});

    function render_preview(data) {
        const errors = data.errors || [];
        const rows = data.rows || [];
        let html = '<div class="table-responsive"><table class="table table-bordered table-condensed">';
        html += '<thead><tr><th>Item Code</th><th>Stock Qty</th><th>Status</th><th>Matching PO</th></tr></thead><tbody>';
        rows.forEach((row) => {
            const good = row.status === "Matched";
            const refs = (row.candidates || []).map((x) => x.po + " / " + x.po_item).join(", ");
            html += '<tr><td>' + escape(row.item_code) + '</td><td>' + escape(row.qty)
                + '</td><td>' + (good ? '<span class="text-success">' : '<span class="text-danger">')
                + escape(row.status) + '</span></td><td>' + escape(refs || row.message || "") + '</td></tr>';
        });
        html += '</tbody></table></div>';
        if (errors.length) {
            html += '<div class="text-danger">' + errors.map(e => escape("Row " + e.row + ": " + e.message)).join("<br>") + '</div>';
        }
        html += '<p><strong>' + escape(data.matched) + ' / ' + escape(data.total)
            + '</strong> item variants matched.</p>';
        return html;
    }

    function open_dialog(frm) {
        if (!frm.is_new() || frm.doc.docstatus !== 0) {
            msg(__("Open a new unsaved Purchase Receipt first."));
            return;
        }
        if ((frm.doc.items || []).length) {
            msg(__("Start with an empty Purchase Receipt. This action does not replace existing item rows."));
            return;
        }
        if (!frm.doc.supplier || !frm.doc.company) {
            msg(__("Select Company and Supplier first."));
            return;
        }
        const dialog = new frappe.ui.Dialog({
            title: __("Bulk Shipment Receiving"),
            size: "extra-large",
            fields: [
                {fieldname: "instructions", fieldtype: "HTML",
                 options: '<p>Copy two Excel columns: <strong>Item Variant Code</strong> and <strong>Actual Received Qty (Stock UOM)</strong>. The tool will match outstanding Purchase Order lines for the selected Supplier and Company. It does not submit stock.</p>'},
                {fieldname: "paste", fieldtype: "Small Text", label: __("Item Code / Received Qty"),
                 reqd: 1, description: __("Paste tab-separated rows from Excel, or two-column CSV.")},
                {fieldname: "preview", fieldtype: "HTML"},
            ],
            primary_action_label: __("Preview Match"),
            primary_action: async () => {
                const values = dialog.get_values();
                if (!values) return;
                dialog.__paste = values.paste;
                const response = await frappe.call({
                    method: API + ".preview",
                    args: {text: values.paste, supplier: frm.doc.supplier, company: frm.doc.company},
                    freeze: true,
                    freeze_message: __("Matching Purchase Orders...")
                });
                const result = response.message || {};
                dialog.fields_dict.preview.$wrapper.html(render_preview(result));
                const ready = result.total > 0 && result.matched === result.total && !(result.errors || []).length;
                dialog.get_secondary_btn().toggle(ready);
            },
            secondary_action_label: __("Load into Draft"),
            secondary_action: async () => {
                const pasted = dialog.get_values()?.paste;
                if (!pasted || pasted !== dialog.__paste) {
                    msg(__("Pasted values changed. Preview again before loading."));
                    return;
                }
                if ((frm.doc.items || []).length) {
                    msg(__("Purchase Receipt already contains items; no changes made."));
                    return;
                }
                const response = await frappe.call({
                    method: API + ".build_draft",
                    args: {text: pasted, supplier: frm.doc.supplier, company: frm.doc.company},
                    freeze: true,
                    freeze_message: __("Preparing draft Purchase Receipt...")
                });
                const mapped = response.message;
                if (!mapped?.items?.length) {
                    msg(__("No matching items returned."));
                    return;
                }
                // Keep the existing unsaved Purchase Receipt and its supplier/company;
                // copy ERPNext-mapped child fields, never internal document identifiers.
                const skip = new Set(["name", "doctype", "parent", "parentfield", "parenttype",
                    "idx", "docstatus", "creation", "modified", "modified_by", "owner", "__islocal"]);
                for (const source of mapped.items) {
                    const target = frm.add_child("items");
                    for (const [key, value] of Object.entries(source)) {
                        if (!skip.has(key)) target[key] = value;
                    }
                }
                frm.refresh_field("items");
                frm.dirty();
                dialog.hide();
                frappe.show_alert({
                    message: __("Matched Purchase Order lines loaded. Review warehouses, quantities, rates, taxes and rejected quantities before saving."),
                    indicator: "green"
                }, 10);
            }
        });
        dialog.show();
        dialog.get_secondary_btn().hide();
    }

    frappe.ui.form.on("Purchase Receipt", {
        refresh(frm) {
            if (frm.doc.docstatus !== 0 || !frm.is_new()) return;
            frm.add_custom_button(__("Bulk Shipment Receiving"), () => open_dialog(frm), __("Get Items From"));
        }
    });
})();
