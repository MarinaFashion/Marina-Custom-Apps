/* Marina Bulk Shipment Receiving UI v2.1: PO-title and variance approvals.
 * Asset path is versioned to prevent a cached v1 script from calling v2 backend.
 */
(() => {
    const API = "marina_custom_apps.purchasing.bulk_shipment_receiving";
    const PAGE_SIZE = 20;
    const escape = value => frappe.utils.escape_html(String(value ?? ""));
    const show_message = text => frappe.msgprint({title: __("Bulk Shipment Receiving"), message: text});
    const number = value => frappe.format(value ?? 0, {fieldtype: "Float", precision: 2});

    function has_item_data(row) {
        return Boolean(row.item_code || row.item_name || row.description ||
            row.purchase_order || row.purchase_order_item || row.qty ||
            row.received_qty || row.rejected_qty || row.rate || row.amount ||
            row.batch_no || row.serial_no);
    }
    function has_existing_items(frm) {
        return (frm.doc.items || []).some(has_item_data);
    }

    function open_dialog(frm) {
        if (!frm.is_new() || frm.doc.docstatus !== 0 || has_existing_items(frm)) {
            show_message(__("Start with a new unsaved Purchase Receipt without entered item rows."));
            return;
        }
        if (!frm.doc.supplier || !frm.doc.company) {
            show_message(__("Select Company and Supplier first."));
            return;
        }
        const dialog = new frappe.ui.Dialog({
            title: __("Bulk Shipment Receiving"),
            size: "extra-large",
            fields: [
                {fieldtype: "HTML", fieldname: "help",
                 options: '<p>Paste Item Variant Code and Actual Received Qty (Stock UOM) from Excel. Variants match Purchase Orders by <strong>Item Template = Purchase Order Title</strong>. Review every page and accept or reject each variance before loading.</p>'},
                {fieldname: "paste", fieldtype: "Small Text", label: __("Variant Code / Received Qty"),
                 reqd: 1, description: __("Two tab-separated Excel columns or CSV.")},
                {fieldtype: "HTML", fieldname: "review"},
            ],
            primary_action_label: __("Preview Match"),
            primary_action: async () => {
                const values = dialog.get_values();
                if (!values) return;
                dialog.__review = null;
                dialog.get_secondary_btn().hide();
                const response = await frappe.call({
                    method: API + ".preview",
                    args: {text: values.paste, company: frm.doc.company, supplier: frm.doc.supplier},
                    freeze: true, freeze_message: __("Matching variants to PO titles...")
                });
                const results = response.message || {};
                const rows = results.rows || [];
                const decisions = {};
                rows.forEach(row => {
                    // Exact match defaults to Accept; all variance/exceptions require review.
                    decisions[row.item_code] = row.status === "Matched" ? "Accept" : "";
                });
                dialog.__review = {paste: values.paste, supplier: frm.doc.supplier,
                    company: frm.doc.company, rows, decisions, selected: new Set(),
                    errors: results.errors || [], page: 0};
                render();
            },
            secondary_action_label: __("Approve and Load Selected"),
            secondary_action: async () => {
                const review = dialog.__review;
                if (!review) return;
                const pasted = dialog.get_values()?.paste;
                if (pasted !== review.paste || review.supplier !== frm.doc.supplier ||
                    review.company !== frm.doc.company) {
                    show_message(__("Input, Supplier or Company changed. Preview again."));
                    return;
                }
                if (has_existing_items(frm)) {
                    show_message(__("Receipt contains entered items; nothing was loaded."));
                    return;
                }
                if (review.errors.length || review.rows.some(row => !review.decisions[row.item_code])) {
                    show_message(__("Review every row and resolve input errors first."));
                    return;
                }
                const decisions = review.rows.map(row => ({
                    item_code: row.item_code,
                    decision: review.decisions[row.item_code],
                    po_item: row.candidates?.length === 1 ? row.candidates[0].po_item : null
                }));
                const response = await frappe.call({
                    method: API + ".build_draft",
                    args: {text: review.paste, supplier: review.supplier,
                        company: review.company, decisions: JSON.stringify(decisions)},
                    freeze: true, freeze_message: __("Building Purchase Receipt draft...")
                });
                const mapped = response.message;
                if (!mapped?.items?.length) {
                    show_message(__("No PO items returned; nothing loaded."));
                    return;
                }
                if (has_existing_items(frm)) {
                    show_message(__("Receipt was edited during matching; nothing loaded."));
                    return;
                }
                frm.clear_table("items");
                const excluded = new Set(["name", "doctype", "parent", "parentfield",
                    "parenttype", "idx", "docstatus", "creation", "modified",
                    "modified_by", "owner", "__islocal"]);
                mapped.items.forEach(source => {
                    const child = frm.add_child("items");
                    Object.entries(source).forEach(([key, value]) => {
                        if (!excluded.has(key)) child[key] = value;
                    });
                });
                frm.refresh_field("items");
                if (typeof frm.cscript?.calculate_taxes_and_totals === "function") {
                    frm.cscript.calculate_taxes_and_totals();
                }
                frm.dirty();
                dialog.hide();
                frappe.show_alert({
                    message: __("Approved lines loaded. Review PO links, received quantities, warehouse, taxes and ERPNext over-receipt tolerance before saving."),
                    indicator: "green"
                }, 10);
            }
        });

        function render() {
            const state = dialog.__review;
            if (!state) return;
            const totalPages = Math.max(1, Math.ceil(state.rows.length / PAGE_SIZE));
            state.page = Math.max(0, Math.min(totalPages - 1, state.page));
            const begin = state.page * PAGE_SIZE;
            const visible = state.rows.slice(begin, begin + PAGE_SIZE);
            const accepted = state.rows.filter(row => state.decisions[row.item_code] === "Accept").length;
            const rejected = state.rows.filter(row => state.decisions[row.item_code] === "Reject").length;
            const remaining = state.rows.length - accepted - rejected;
            const eligible = state.rows.filter(row => ["Matched", "Variance"].includes(row.status));
            const selected = eligible.filter(row => state.selected.has(row.item_code));
            const excess = selected.filter(row => Number(row.variance) > 0.000001);
            const $root = dialog.fields_dict.review.$wrapper;
            let html = '<div class="mb-2"><strong>' + escape(state.rows.length) +
                '</strong> variants · <span class="text-success">' + escape(accepted) +
                ' accepted</span> · <span class="text-danger">' + escape(rejected) +
                ' rejected</span> · <strong>' + escape(remaining) + ' to review</strong> · ' +
                '<strong>' + escape(selected.length) + ' selected</strong></div>' +
                '<div class="d-flex align-items-center" style="gap:6px;flex-wrap:wrap;margin-bottom:10px">' +
                '<button class="btn btn-default btn-sm marina-select-all">Select All Eligible (' + eligible.length + ')</button>' +
                '<button class="btn btn-default btn-sm marina-clear-selection">Clear Selection</button>' +
                '<button class="btn btn-primary btn-sm marina-approve-selected"' +
                (selected.length ? '' : ' disabled') + '>Approve Selected (' + selected.length + ')</button>' +
                '</div>';
            if (state.errors.length) {
                html += '<p class="text-danger">' + state.errors.map(e =>
                    escape("Row " + e.row + ": " + e.message)).join("<br>") + '</p>';
            }
            html += '<div class="table-responsive" style="max-height:480px;overflow:auto;">';
            html += '<table class="table table-bordered table-condensed"><thead><tr>' +
                '<th>Item Variant</th><th>PO Title</th><th>PO Qty</th>' +
                '<th>Outstanding</th><th>Receipt Qty</th><th>Variance</th>' +
                '<th>Status</th><th>Decision</th><th>Select</th></tr></thead><tbody>';
            visible.forEach((row, index) => {
                const po = row.candidates?.length === 1 ? row.candidates[0] : null;
                const valid = row.status === "Matched" || row.status === "Variance";
                const variance = row.variance;
                const decision = state.decisions[row.item_code] || "";
                const options = valid ?
                    '<option value="">Review</option><option value="Accept"' +
                    (decision === "Accept" ? " selected" : "") + '>Accept</option>' +
                    '<option value="Reject"' + (decision === "Reject" ? " selected" : "") + '>Reject</option>' :
                    '<option value="">Review</option><option value="Reject"' +
                    (decision === "Reject" ? " selected" : "") + '>Reject</option>';
                html += '<tr><td>' + escape(row.item_code) + '</td>' +
                    '<td>' + escape(row.po_title || row.template || "") + '</td>' +
                    '<td class="text-right">' + (po ? number(row.po_qty) : "—") + '</td>' +
                    '<td class="text-right">' + (po ? number(row.outstanding_qty) : "—") + '</td>' +
                    '<td class="text-right">' + number(row.receipt_qty) + '</td>' +
                    '<td class="text-right">' + (variance == null ? "—" : number(variance)) + '</td>' +
                    '<td class="' + (valid ? "text-success" : "text-danger") + '">' +
                    escape(row.status) + '</td>' +
                    '<td><select class="form-control input-xs marina-decision" data-index="' +
                    (begin + index) + '">' + options + '</select></td>' +
                    '<td class="text-center"><input type="checkbox" class="marina-row-select" data-index="' +
                    (begin + index) + '"' + (valid ? '' : ' disabled') +
                    (state.selected.has(row.item_code) ? ' checked' : '') + '></td></tr>';
            });
            html += '</tbody></table></div>';
            html += '<div class="d-flex align-items-center justify-content-between mt-3">' +
                '<div><button class="btn btn-default btn-sm marina-prev"' +
                (state.page === 0 ? " disabled" : "") + '>Previous</button> ' +
                '<button class="btn btn-default btn-sm marina-next"' +
                (state.page >= totalPages - 1 ? " disabled" : "") + '>Next</button> ' +
                ' Page ' + (state.page + 1) + ' / ' + totalPages + '</div>' +
                '<div><button class="btn btn-default btn-sm marina-accept-page">Accept eligible on page</button> ' +
                '<button class="btn btn-default btn-sm marina-reject-page">Reject page</button></div></div>';
            html += '<p class="text-muted small mt-2">Variance = Receipt Qty − Outstanding Qty (Stock UOM). ' +
                'Accept does not bypass ERPNext over-receipt controls. Unmatched rows can only be rejected.</p>';
            $root.html(html);
            $root.find(".marina-decision").on("change", function() {
                const row = state.rows[Number($(this).attr("data-index"))];
                state.decisions[row.item_code] = $(this).val();
                render();
            });
            $root.find(".marina-row-select").on("change", function() {
                const row = state.rows[Number($(this).attr("data-index"))];
                if ($(this).prop("checked")) state.selected.add(row.item_code);
                else state.selected.delete(row.item_code);
                render();
            });
            $root.find(".marina-select-all").on("click", () => {
                eligible.forEach(row => state.selected.add(row.item_code));
                render();
            });
            $root.find(".marina-clear-selection").on("click", () => {
                state.selected.clear();
                render();
            });
            $root.find(".marina-approve-selected").on("click", () => {
                if (!selected.length) return;
                const apply = () => {
                    selected.forEach(row => {state.decisions[row.item_code] = "Accept";});
                    render();
                };
                if (excess.length) {
                    const excessQty = excess.reduce((sum, row) => sum + Number(row.variance), 0);
                    frappe.confirm(
                        __("You are accepting {0} rows with quantities ABOVE the outstanding PO balance (total excess {1} stock units). ERPNext over-receipt limits will still apply. Continue?", [excess.length, number(excessQty)]),
                        apply
                    );
                } else apply();
            });
            $root.find(".marina-prev").on("click", () => {state.page -= 1; render();});
            $root.find(".marina-next").on("click", () => {state.page += 1; render();});
            $root.find(".marina-accept-page").on("click", () => {
                visible.filter(r => ["Matched", "Variance"].includes(r.status)).forEach(r => {
                    state.decisions[r.item_code] = "Accept";
                });
                render();
            });
            $root.find(".marina-reject-page").on("click", () => {
                visible.forEach(r => {state.decisions[r.item_code] = "Reject";});
                render();
            });
            dialog.get_secondary_btn().toggle(
                !state.errors.length && state.rows.length > 0 &&
                remaining === 0 && accepted > 0
            );
        }

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
