/* Marina Bulk Shipment Receiving UI v4: controlled receipts without an available PO.
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
                    // Exact match defaults to Accept; exceptions ALWAYS need explicit review.
                    decisions[row.item_code] = row.status === "Matched" ? "Accept" : "";
                });
                dialog.__review = {paste: values.paste, supplier: frm.doc.supplier,
                    company: frm.doc.company, rows, decisions, selected: new Set(),
                    exceptionRates: {}, exceptionWarehouses: {},
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
                const invalidException = review.rows.find(row =>
                    review.decisions[row.item_code] === "Receive Without PO" &&
                    (!(Number(review.exceptionRates[row.item_code]) > 0) ||
                     !(review.exceptionWarehouses[row.item_code] || "").trim()));
                if (invalidException) {
                    show_message(__("Enter a purchase rate and warehouse for {0} before loading.", [invalidException.item_code]));
                    return;
                }
                const decisions = review.rows.map(row => ({
                    item_code: row.item_code,
                    decision: review.decisions[row.item_code],
                    po_item: review.decisions[row.item_code] === "Accept" && row.candidates?.length === 1 ? row.candidates[0].po_item : null,
                    rate: review.exceptionRates[row.item_code],
                    warehouse: review.exceptionWarehouses[row.item_code]
                }));
                const response = await frappe.call({
                    method: API + ".build_draft",
                    args: {text: review.paste, supplier: review.supplier,
                        company: review.company, decisions: JSON.stringify(decisions),
                        currency: frm.doc.currency, conversion_rate: frm.doc.conversion_rate},
                    freeze: true, freeze_message: __("Building Purchase Receipt draft...")
                });
                const mapped = response.message;
                if (!mapped?.items?.length) {
                    show_message(__("No approved items returned; nothing loaded."));
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
                    message: __("Approved PO-linked and unlinked rows loaded. Review rates, unlinked PO references, warehouse, currency, taxes and totals before saving."),
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
            const accepted = state.rows.filter(row => ["Accept", "Receive Without PO"].includes(state.decisions[row.item_code])).length;
            const rejected = state.rows.filter(row => state.decisions[row.item_code] === "Reject").length;
            const remaining = state.rows.length - accepted - rejected;
            const eligible = state.rows.filter(row => ["Matched", "Variance", "No Available PO"].includes(row.status));
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
                '<button class="btn btn-default btn-sm marina-reject-unmatched">Reject Invalid / Ambiguous</button>' +
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
                const valid = ["Matched", "Variance", "No Available PO"].includes(row.status);
                const unlinked = row.status === "No Available PO";
                const variance = row.variance;
                const decision = state.decisions[row.item_code] || "";
                const options = '<option value="">Review</option>' +
                    (!unlinked && valid ? '<option value="Accept"' +
                        (decision === "Accept" ? " selected" : "") + '>Accept PO-linked</option>' : '') +
                    (unlinked ? '<option value="Receive Without PO"' +
                        (decision === "Receive Without PO" ? " selected" : "") +
                        '>Receive Without PO</option>' : '') +
                    '<option value="Reject"' + (decision === "Reject" ? " selected" : "") +
                    '>Reject</option>';
                html += '<tr><td title="' + escape(row.message || "") + '">' + escape(row.item_code) + '</td>' +
                    '<td>' + escape(row.po_title || row.template || "") + '</td>' +
                    '<td class="text-right">' + (po ? number(row.po_qty) : "—") + '</td>' +
                    '<td class="text-right">' + (po ? number(row.outstanding_qty) : "—") + '</td>' +
                    '<td class="text-right">' + number(row.receipt_qty) + '</td>' +
                    '<td class="text-right">' + (variance == null ? "—" : number(variance)) + '</td>' +
                    '<td class="' + (unlinked ? "text-warning" : valid ? "text-success" : "text-danger") + '">' +
                    escape(row.status) + '</td>' +
                    '<td><select class="form-control input-xs marina-decision" data-index="' +
                    (begin + index) + '">' + options + '</select>' +
                    (unlinked && decision === "Receive Without PO" ?
                    '<div style="min-width:135px;padding-top:5px"><label>Rate (' +
                    escape(frm.doc.currency || "currency") + ')</label><input type="number" min="0.000001" step="any" class="form-control input-xs marina-exception-rate" data-index="' +
                    (begin + index) + '" value="' + escape(state.exceptionRates[row.item_code] ?? "") +
                    '"><label>Warehouse</label><input class="form-control input-xs marina-exception-warehouse" data-index="' +
                    (begin + index) + '" value="' + escape(state.exceptionWarehouses[row.item_code] ?? frm.doc.set_warehouse ?? "") +
                    '"></div>' : '') + '</td>' +
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
                'No Available PO rows require Receive Without PO plus an explicit transaction-currency rate and company warehouse. ' +
                'These rows do not link to any completed/closed PO and remain subject to ERPNext validation.</p>';
            $root.html(html);
            $root.find(".marina-decision").on("change", function() {
                const row = state.rows[Number($(this).attr("data-index"))];
                state.decisions[row.item_code] = $(this).val();
                if (state.decisions[row.item_code] === "Receive Without PO" && !state.exceptionWarehouses[row.item_code]) {
                    state.exceptionWarehouses[row.item_code] = frm.doc.set_warehouse || "";
                }
                render();
            });
            $root.find(".marina-exception-rate").on("change input", function() {
                const row = state.rows[Number($(this).attr("data-index"))];
                state.exceptionRates[row.item_code] = $(this).val();
            });
            $root.find(".marina-exception-warehouse").on("change input", function() {
                const row = state.rows[Number($(this).attr("data-index"))];
                state.exceptionWarehouses[row.item_code] = $(this).val();
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
            $root.find(".marina-reject-unmatched").on("click", () => {
                state.rows.filter(row => !["Matched", "Variance", "No Available PO"].includes(row.status))
                    .forEach(row => {state.decisions[row.item_code] = "Reject";});
                render();
            });
            $root.find(".marina-approve-selected").on("click", () => {
                if (!selected.length) return;
                const apply = () => {
                    selected.forEach(row => {
                        state.decisions[row.item_code] = row.status === "No Available PO" ? "Receive Without PO" : "Accept";
                        if (row.status === "No Available PO" && !state.exceptionWarehouses[row.item_code]) {
                            state.exceptionWarehouses[row.item_code] = frm.doc.set_warehouse || "";
                        }
                    });
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
                visible.filter(r => ["Matched", "Variance", "No Available PO"].includes(r.status)).forEach(r => {
                    state.decisions[r.item_code] = r.status === "No Available PO" ? "Receive Without PO" : "Accept";
                    if (r.status === "No Available PO" && !state.exceptionWarehouses[r.item_code]) {
                        state.exceptionWarehouses[r.item_code] = frm.doc.set_warehouse || "";
                    }
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
