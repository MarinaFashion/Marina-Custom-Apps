const POS_RECON_PAGE_LENGTH = 25;

frappe.ui.form.on("POS Reconciliation Run", {
    refresh(frm) {
        if (frm.is_new()) {
            return;
        }

        if (frm.doc.status === "Draft") {
            frm.set_intro(
                __("Click Run Reconciliation to load and compare the approved Bank POS and Alhamrani transactions for this period."),
                "blue"
            );
        } else if (frm.doc.status === "Completed") {
            frm.set_intro(
                __("This run is completed. Review source transactions and Finance exceptions below. Use Re-run Reconciliation if source data changed."),
                "green"
            );
        }

        const run_label = frm.doc.status === "Completed"
            ? __("Re-run Reconciliation")
            : __("Run Reconciliation");

        if (frm.doc.status !== "Running" && !frm.is_dirty()) {
            const run_button = frm.add_custom_button(run_label, () => {
                frappe.confirm(
                    __("Reconcile approved Bank POS transactions against approved Alhamrani transactions for this period?"),
                    () => {
                        frappe.call({
                            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.run_reconciliation",
                            args: { run_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __("Reconciling POS transactions..."),
                        }).then((r) => {
                            const result = r.message || {};
                            const bank_pending = Math.max(cint(result.bank_only_count || 0) - cint(result.manually_cleared_count || 0), 0);
                            frm.reload_doc();
                            frappe.msgprint({
                                title: __("Reconciliation Completed"),
                                indicator: result.pending_count ? "orange" : "green",
                                message: __(
                                    "Matching: {0}<br>Discrepancies: {1}<br>Bank Pending: {2}<br>Marina Pending: {3}<br>Manually Cleared: {4}<br>All Pending: {5}",
                                    [
                                        result.matching_count || 0,
                                        result.discrepancy_count || 0,
                                        bank_pending,
                                        result.alhamrani_only_count || 0,
                                        result.manually_cleared_count || 0,
                                        result.pending_count || 0,
                                    ]
                                ),
                            });
                        });
                    }
                );
            });
            run_button.addClass("btn-primary");
        }

        frm.add_custom_button(__("All Records"), () => {
            frappe.set_route("List", "POS Reconciliation Record", { run: frm.doc.name });
        }, __("View"));

        frm.add_custom_button(__("All Pending"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Matching"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Matching",
            });
        }, __("View"));

        frm.add_custom_button(__("Discrepancies"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Discrepancy",
            });
        }, __("View"));

        frm.add_custom_button(__("Bank Pending"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Bank Only",
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Marina Pending"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Alhamrani Only",
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Manually Cleared"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                resolution_status: "Manually Cleared",
            });
        }, __("View"));

        frm.add_custom_button(__("Reconciliation Settings"), () => {
            frappe.set_route("Form", "POS Reconciliation Settings", "POS Reconciliation Settings");
        }, __("View"));

        if (frm.doc.status === "Completed") {
            frm.add_custom_button(__("Pending Accounting"), () => {
                frappe.set_route("List", "POS Reconciliation Record", {
                    run: frm.doc.name,
                    accounting_status: "Pending Accounting",
                });
            }, __("Accounting"));

            frm.add_custom_button(__("Posted"), () => {
                frappe.set_route("List", "POS Reconciliation Record", {
                    run: frm.doc.name,
                    accounting_status: "Posted",
                });
            }, __("Accounting"));

            frm.add_custom_button(__("Review Required"), () => {
                frappe.set_route("List", "POS Reconciliation Record", {
                    run: frm.doc.name,
                    accounting_status: "Posted - Review Required",
                });
            }, __("Accounting"));

            frm.add_custom_button(__("Accounting Postings"), () => {
                frappe.set_route("List", "POS Accounting Posting", { source_run: frm.doc.name });
            }, __("Accounting"));

            frm.add_custom_button(__("Create Journal Entries"), () => {
                pos_recon_open_accounting_dialog(frm);
            }, __("Accounting"));

            pos_recon_setup_review(frm);
        }
    },
});


function pos_recon_setup_review(frm) {
    if (!frm.__pos_recon_review) {
        frm.__pos_recon_review = {
            bank: { start: 0, search: "" },
            alhamrani: { start: 0, search: "" },
            results: {
                start: 0,
                search: "",
                status: "All",
                from_date: frm.doc.from_date || "",
                to_date: frm.doc.to_date || "",
                settlement_number: "",
                settlement_date: "",
                pos_profile: "",
                terminal_id: "",
                card_type: "",
                finance_review_status: "",
                before_integration: "All",
                options: { settlement_numbers: [], pos_profiles: [], terminal_ids: [], card_types: [] },
            },
        };
    }

    pos_recon_load_source(frm, "bank");
    pos_recon_load_source(frm, "alhamrani");
    pos_recon_load_filter_options(frm).then(() => pos_recon_load_results(frm));
}


function pos_recon_load_filter_options(frm) {
    const state = frm.__pos_recon_review.results;
    return frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_review_filter_options",
        args: { run_name: frm.doc.name, status: "All" },
    }).then((r) => {
        state.options = r.message || { settlement_numbers: [], pos_profiles: [], terminal_ids: [], card_types: [] };
    });
}

function pos_recon_load_source(frm, source) {
    const state = frm.__pos_recon_review[source];
    const fieldname = source === "bank" ? "bank_source_review" : "alhamrani_source_review";
    const field = frm.fields_dict[fieldname];

    if (!field || !field.$wrapper) {
        return;
    }

    pos_recon_render_loading(field.$wrapper);

    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_source_review_page",
        args: {
            run_name: frm.doc.name,
            source: source,
            start: state.start,
            page_length: POS_RECON_PAGE_LENGTH,
            search: state.search,
        },
    }).then((r) => {
        pos_recon_render_source(frm, source, field.$wrapper, r.message || {});
    });
}


function pos_recon_load_results(frm) {
    const state = frm.__pos_recon_review.results;
    const field = frm.fields_dict.results_review_html;

    if (!field || !field.$wrapper) {
        return;
    }

    pos_recon_render_loading(field.$wrapper);

    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_results_review_page",
        args: {
            run_name: frm.doc.name,
            status: state.status,
            start: state.start,
            page_length: POS_RECON_PAGE_LENGTH,
            search: state.search,
            from_date: state.from_date,
            to_date: state.to_date,
            settlement_number: state.settlement_number,
            settlement_date: state.settlement_date,
            pos_profile: state.pos_profile,
            terminal_id: state.terminal_id,
            card_type: state.card_type,
            finance_review_status: state.finance_review_status,
            before_integration: state.before_integration,
        },
    }).then((r) => {
        pos_recon_render_results(frm, field.$wrapper, r.message || {});
    });
}


function pos_recon_render_source(frm, source, $wrapper, data) {
    const state = frm.__pos_recon_review[source];
    const title = source === "bank" ? __("Bank POS Transactions") : __("Alhamrani Transactions");
    const doctype = source === "bank" ? "Bank POS Transaction" : "Alhamrani Transaction";
    const rows = data.rows || [];
    const total = cint(data.total || 0);
    const start = cint(data.start || 0);
    const page_length = cint(data.page_length || POS_RECON_PAGE_LENGTH);

    const body = rows.length
        ? rows.map((row) => `
            <tr>
                <td>${pos_recon_doc_link(doctype, row.name)}</td>
                <td>${pos_recon_escape(row.transaction_date)}</td>
                <td>${pos_recon_escape(row.transaction_time)}</td>
                <td>${pos_recon_escape(row.terminal_id)}</td>
                <td>${pos_recon_escape(row.rrn)}</td>
                <td>${pos_recon_escape(row.auth_code)}</td>
                <td>${pos_recon_escape(row.transaction_type)}</td>
                <td class="text-right">${pos_recon_money(row.amount)}</td>
                <td>${pos_recon_escape(row.card_type)}</td>
                <td>${pos_recon_status_pill(row.match_status)}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="10" class="text-muted text-center">${__("No transactions found")}</td></tr>`;

    $wrapper.html(`
        ${pos_recon_styles()}
        <div class="pos-recon-panel">
            <div class="pos-recon-panel-head">
                <div>
                    <div class="pos-recon-title">${title}</div>
                    <div class="text-muted small">${__("Primary identity: Terminal ID + RRN + Auth Code + Transaction Type")}</div>
                </div>
                <button class="btn btn-xs btn-default pos-recon-open-list">${__("Open List")}</button>
            </div>
            <div class="pos-recon-toolbar">
                <input type="text" class="form-control input-xs pos-recon-search"
                    placeholder="${__("Search reference, terminal, profile or status")}" value="${pos_recon_escape(state.search)}">
                <span class="text-muted small">${pos_recon_range_text(start, rows.length, total)}</span>
            </div>
            <div class="pos-recon-table-wrap">
                <table class="table table-bordered table-hover pos-recon-table">
                    <thead><tr>
                        <th>${__("Reference")}</th><th>${__("Date")}</th><th>${__("Time")}</th>
                        <th>${__("Terminal ID")}</th><th>${__("RRN")}</th><th>${__("Auth")}</th>
                        <th>${__("Type")}</th><th class="text-right">${__("Amount")}</th>
                        <th>${__("Card")}</th><th>${__("Result")}</th>
                    </tr></thead>
                    <tbody>${body}</tbody>
                </table>
            </div>
            ${pos_recon_pager(start, page_length, total)}
        </div>
    `);

    pos_recon_bind_doc_links($wrapper);
    $wrapper.find(".pos-recon-open-list").on("click", () => frappe.set_route("List", doctype));
    pos_recon_bind_search($wrapper, (value) => {
        state.search = value;
        state.start = 0;
        pos_recon_load_source(frm, source);
    });
    pos_recon_bind_pager($wrapper, start, page_length, total, (next_start) => {
        state.start = next_start;
        pos_recon_load_source(frm, source);
    });
}


function pos_recon_render_results(frm, $wrapper, data) {
    const state = frm.__pos_recon_review.results;
    const rows = data.rows || [];
    const total = cint(data.total || 0);
    const start = cint(data.start || 0);
    const page_length = cint(data.page_length || POS_RECON_PAGE_LENGTH);
    const is_bank_only = state.status === "Bank Pending";
    const bank_pending_count = Math.max(cint(frm.doc.bank_only_count || 0) - cint(frm.doc.manually_cleared_count || 0), 0);
    const marina_pending_count = cint(frm.doc.alhamrani_only_count || 0);

    const statuses = [
        ["All", __("All"), pos_recon_total_results(frm)],
        ["Matching", __("Matching"), cint(frm.doc.matching_count || 0)],
        ["Discrepancy", __("Discrepancies"), cint(frm.doc.discrepancy_count || 0)],
        ["Bank Pending", __("Bank Pending"), bank_pending_count],
        ["Marina Pending", __("Marina Pending"), marina_pending_count],
        ["Manually Cleared", __("Manually Cleared"), cint(frm.doc.manually_cleared_count || 0)],
        ["All Pending", __("All Pending"), cint(frm.doc.pending_count || 0)],
    ];

    const filter_buttons = statuses.map(([value, label, count]) => `
        <button class="btn btn-xs ${state.status === value ? "btn-primary" : "btn-default"} pos-recon-status-filter"
            data-status="${pos_recon_escape(value)}">${label} <span class="badge">${count}</span></button>
    `).join("");

    const review_filters = pos_recon_result_filters(state, state.options || {}, is_bank_only, data.settlement_summary);
    const checkbox_head = is_bank_only ? `<th style="width:32px"><input type="checkbox" class="pos-recon-select-page"></th>` : "";

    const body = rows.length
        ? rows.map((row) => {
            const details = [
                row.discrepancy_fields || "",
                row.before_integration ? __("Before Integration") : "",
                row.finance_review_note || "",
                row.manual_clearance_reason || "",
            ].filter(Boolean).join(" · ");
            const actionable = is_bank_only && row.resolution_status === "Pending";
            const checkbox = is_bank_only
                ? (actionable
                    ? `<td><input type="checkbox" class="pos-recon-row-check"
                        data-record="${pos_recon_escape(row.name)}"
                        data-gross="${Number(row.bank_amount || 0)}"
                        data-commission="${Number(row.bank_commission_amount || 0)}"
                        data-vat="${Number(row.bank_commission_vat_amount || 0)}"></td>`
                    : `<td></td>`)
                : "";

            return `
                <tr>
                    ${checkbox}
                    <td>${row.bank_transaction ? pos_recon_doc_link("Bank POS Transaction", row.bank_transaction) : "—"}</td>
                    <td>${row.alhamrani_transaction ? pos_recon_doc_link("Alhamrani Transaction", row.alhamrani_transaction) : "—"}</td>
                    <td>${pos_recon_escape(row.transaction_date)}</td>
                    <td>${pos_recon_escape(row.pos_profile || "—")}</td>
                    <td>${pos_recon_escape(row.terminal_id)}</td>
                    <td>${pos_recon_escape(row.settlement_number || "—")}</td>
                    <td>${pos_recon_status_pill(row.match_status)}</td>
                    <td class="text-right">${pos_recon_money(row.bank_amount)}</td>
                    <td class="text-right">${pos_recon_money(row.alhamrani_amount)}</td>
                    <td class="text-right">${pos_recon_money(row.amount_difference)}</td>
                    <td>${pos_recon_escape(row.pan_validation_method || "—")}</td>
                    <td>${pos_recon_finance_pill(row.finance_review_status)}</td>
                    <td>${pos_recon_escape(details || "—")}</td>
                    <td>${pos_recon_resolution_pill(row.resolution_status)}</td>
                </tr>
            `;
        }).join("")
        : `<tr><td colspan="${is_bank_only ? 16 : 15}" class="text-muted text-center">${__("No reconciliation records found")}</td></tr>`;

    const selected_summary = is_bank_only ? `
        <div class="pos-recon-selected-summary" style="display:none">
            <div><b>${__("Selected")}</b><span class="pos-recon-selected-count">0</span></div>
            <div><b>${__("Gross")}</b><span class="pos-recon-selected-gross">${pos_recon_money(0)}</span></div>
            <div><b>${__("Commission")}</b><span class="pos-recon-selected-commission">${pos_recon_money(0)}</span></div>
            <div><b>${__("VAT")}</b><span class="pos-recon-selected-vat">${pos_recon_money(0)}</span></div>
            <div><b>${__("Expected Net")}</b><span class="pos-recon-selected-net">${pos_recon_money(0)}</span></div>
        </div>` : "";

    $wrapper.html(`
        ${pos_recon_styles()}
        <div class="pos-recon-panel">
            <div class="pos-recon-panel-head">
                <div>
                    <div class="pos-recon-title">${__("Reconciliation Results")}</div>
                    <div class="text-muted small">
                        ${__("Primary match remains Terminal ID + RRN + Auth Code + Transaction Type. PAN validates directly first; if different, Bank PAN last 4 is checked against Alhamrani ECR_EMVData last 4.")}
                    </div>
                </div>
                <button class="btn btn-xs btn-default pos-recon-open-results">${__("Open Full List")}</button>
            </div>
            <div class="pos-recon-result-filters">${filter_buttons}</div>
            ${review_filters}
            ${selected_summary}
            <div class="pos-recon-toolbar">
                <input type="text" class="form-control input-xs pos-recon-search"
                    placeholder="${__("Search transaction, terminal, profile, settlement or status")}" value="${pos_recon_escape(state.search)}">
                <span class="text-muted small">${pos_recon_range_text(start, rows.length, total)}</span>
            </div>
            <div class="pos-recon-table-wrap">
                <table class="table table-bordered table-hover pos-recon-table pos-recon-results-table">
                    <thead><tr>
                        ${checkbox_head}
                        <th>${__("Bank Transaction")}</th><th>${__("Alhamrani Transaction")}</th>
                        <th>${__("Date")}</th><th>${__("POS Profile")}</th><th>${__("Terminal ID")}</th><th>${__("Settlement No.")}</th>
                        <th>${__("Status")}</th><th class="text-right">${__("Bank Amount")}</th>
                        <th class="text-right">${__("Alhamrani Amount")}</th><th class="text-right">${__("Difference")}</th>
                        <th>${__("PAN Validation")}</th><th>${__("Finance Review")}</th><th>${__("Accounting")}</th>
                        <th>${__("Discrepancy / Note")}</th><th>${__("Resolution")}</th>
                    </tr></thead>
                    <tbody>${body}</tbody>
                </table>
            </div>
            ${pos_recon_pager(start, page_length, total)}
        </div>
    `);

    pos_recon_bind_doc_links($wrapper);
    $wrapper.find(".pos-recon-open-results").on("click", () => {
        frappe.set_route("List", "POS Reconciliation Record", { run: frm.doc.name });
    });

    $wrapper.find(".pos-recon-status-filter").on("click", function () {
        state.status = $(this).attr("data-status") || "All";
        state.start = 0;
        pos_recon_load_results(frm);
    });

    pos_recon_bind_result_filters(frm, $wrapper, data, is_bank_only);

    pos_recon_bind_search($wrapper, (value) => {
        state.search = value;
        state.start = 0;
        pos_recon_load_results(frm);
    });
    pos_recon_bind_pager($wrapper, start, page_length, total, (next_start) => {
        state.start = next_start;
        pos_recon_load_results(frm);
    });
}


function pos_recon_result_filters(state, options, is_bank_only, summary) {
    const summary_html = is_bank_only && summary ? `
        <div class="pos-recon-settlement-summary">
            <div><b>${__("Transactions")}</b><span>${cint(summary.transaction_count || 0)}</span></div>
            <div><b>${__("Gross")}</b><span>${pos_recon_money(summary.gross_amount)}</span></div>
            <div><b>${__("Commission")}</b><span>${pos_recon_money(summary.commission)}</span></div>
            <div><b>${__("VAT")}</b><span>${pos_recon_money(summary.vat)}</span></div>
            <div><b>${__("Expected Net")}</b><span>${pos_recon_money(summary.expected_net)}</span></div>
            <div><b>${__("Approved")}</b><span>${cint(summary.approved_count || 0)}</span></div>
            <div><b>${__("Needs Investigation")}</b><span>${cint(summary.investigation_count || 0)}</span></div>
            <div><b>${__("Pending Review")}</b><span>${cint(summary.pending_review_count || 0)}</span></div>
        </div>
        ${(cint(summary.settlement_date_count || 0) > 1 || cint(summary.terminal_count || 0) > 1) ? `
            <div class="alert alert-warning pos-recon-settlement-warning">
                ${__("This Settlement Number spans {0} settlement dates and {1} terminals in the current filters. Narrow the filters to one settlement group before bulk approval.", [summary.settlement_date_count || 0, summary.terminal_count || 0])}
            </div>` : ""}
    ` : (is_bank_only ? `<div class="text-muted small pos-recon-summary-hint">${__("Choose a Settlement Number to show settlement totals and enable controlled Finance audit.")}</div>` : "");

    const finance_fields = is_bank_only ? `
        <div><label>${__("Finance Review")}</label><select class="form-control input-xs pos-recon-filter-finance">
            <option value="">${__("All")}</option>
            ${pos_recon_option("Pending Review", state.finance_review_status)}
            ${pos_recon_option("Checked & Approved", state.finance_review_status)}
            ${pos_recon_option("Needs Investigation", state.finance_review_status)}
        </select></div>
        <div><label>${__("Before Integration")}</label><select class="form-control input-xs pos-recon-filter-before">
            <option value="All" ${state.before_integration === "All" ? "selected" : ""}>${__("All")}</option>
            <option value="1" ${String(state.before_integration) === "1" ? "selected" : ""}>${__("Yes")}</option>
            <option value="0" ${String(state.before_integration) === "0" ? "selected" : ""}>${__("No")}</option>
        </select></div>` : "";

    const multiple_groups = summary && (cint(summary.settlement_date_count || 0) > 1 || cint(summary.terminal_count || 0) > 1);
    const filtered_disabled = !is_bank_only || multiple_groups || !state.settlement_number ? "disabled" : "";
    const finance_actions = is_bank_only ? `
        <div class="pos-recon-finance-actions">
            <button class="btn btn-xs btn-primary pos-recon-approve-selected">${__("Checked & Approved – Selected")}</button>
            <button class="btn btn-xs btn-default pos-recon-investigate-selected">${__("Needs Investigation – Selected")}</button>
            <button class="btn btn-xs btn-default pos-recon-reset-selected">${__("Reset Selected")}</button>
            <span class="pos-recon-action-spacer"></span>
            <button class="btn btn-xs btn-primary pos-recon-approve-filtered" ${filtered_disabled}>${__("Checked & Approved – All Filtered")}</button>
            <button class="btn btn-xs btn-default pos-recon-investigate-filtered" ${filtered_disabled}>${__("Needs Investigation – All Filtered")}</button>
        </div>` : "";

    return `
        <div class="pos-recon-bank-review">
            <div class="pos-recon-bank-filter-grid">
                <div><label>${__("From Date")}</label><input type="date" class="form-control input-xs pos-recon-filter-from-date" value="${pos_recon_escape(state.from_date)}"></div>
                <div><label>${__("To Date")}</label><input type="date" class="form-control input-xs pos-recon-filter-to-date" value="${pos_recon_escape(state.to_date)}"></div>
                <div><label>${__("Settlement Number")}</label><select class="form-control input-xs pos-recon-filter-settlement">${pos_recon_select_options(options.settlement_numbers || [], state.settlement_number, __("All"))}</select></div>
                <div><label>${__("POS Profile")}</label><select class="form-control input-xs pos-recon-filter-profile">${pos_recon_select_options(options.pos_profiles || [], state.pos_profile, __("All"))}</select></div>
                <div><label>${__("Terminal ID")}</label><select class="form-control input-xs pos-recon-filter-terminal">${pos_recon_select_options(options.terminal_ids || [], state.terminal_id, __("All"))}</select></div>
                <div><label>${__("Card Type")}</label><select class="form-control input-xs pos-recon-filter-card">${pos_recon_select_options(options.card_types || [], state.card_type, __("All"))}</select></div>
                ${finance_fields}
                <div class="pos-recon-filter-actions"><button class="btn btn-xs btn-primary pos-recon-apply-bank-filters">${__("Apply Filters")}</button><button class="btn btn-xs btn-default pos-recon-clear-bank-filters">${__("Clear")}</button></div>
            </div>
            ${summary_html}
            ${finance_actions}
        </div>`;
}


function pos_recon_select_options(values, current, all_label) {
    const items = [`<option value="">${pos_recon_escape(all_label || __("All"))}</option>`];
    (values || []).forEach((value) => {
        const selected = String(current || "") === String(value) ? "selected" : "";
        items.push(`<option value="${pos_recon_escape(value)}" ${selected}>${pos_recon_escape(value)}</option>`);
    });
    return items.join("");
}

function pos_recon_option(value, current) {
    return `<option value="${pos_recon_escape(value)}" ${current === value ? "selected" : ""}>${__(value)}</option>`;
}


function pos_recon_bind_result_filters(frm, $wrapper, data, is_bank_only) {
    const state = frm.__pos_recon_review.results;

    $wrapper.find(".pos-recon-apply-bank-filters").on("click", () => {
        state.from_date = $wrapper.find(".pos-recon-filter-from-date").val() || "";
        state.to_date = $wrapper.find(".pos-recon-filter-to-date").val() || "";
        state.settlement_number = $wrapper.find(".pos-recon-filter-settlement").val() || "";
        state.pos_profile = $wrapper.find(".pos-recon-filter-profile").val() || "";
        state.terminal_id = $wrapper.find(".pos-recon-filter-terminal").val() || "";
        state.card_type = $wrapper.find(".pos-recon-filter-card").val() || "";
        if (is_bank_only) {
            state.finance_review_status = $wrapper.find(".pos-recon-filter-finance").val() || "";
            state.before_integration = $wrapper.find(".pos-recon-filter-before").val() || "All";
        }
        state.start = 0;
        pos_recon_load_results(frm);
    });

    $wrapper.find(".pos-recon-clear-bank-filters").on("click", () => {
        state.from_date = frm.doc.from_date || "";
        state.to_date = frm.doc.to_date || "";
        state.settlement_number = "";
        state.settlement_date = "";
        state.pos_profile = "";
        state.terminal_id = "";
        state.card_type = "";
        state.finance_review_status = "";
        state.before_integration = "All";
        state.start = 0;
        pos_recon_load_results(frm);
    });

    if (!is_bank_only) return;

    const update_selection = () => pos_recon_update_selected_summary($wrapper);
    $wrapper.find(".pos-recon-select-page").on("change", function () {
        $wrapper.find(".pos-recon-row-check").prop("checked", $(this).prop("checked"));
        update_selection();
    });
    $wrapper.find(".pos-recon-row-check").on("change", update_selection);

    $wrapper.find(".pos-recon-approve-selected").on("click", () => pos_recon_review_selected(frm, $wrapper, "Checked & Approved"));
    $wrapper.find(".pos-recon-investigate-selected").on("click", () => pos_recon_review_selected(frm, $wrapper, "Needs Investigation"));
    $wrapper.find(".pos-recon-reset-selected").on("click", () => pos_recon_reset_selected(frm, $wrapper));
    $wrapper.find(".pos-recon-approve-filtered").on("click", () => pos_recon_review_filtered(frm, data, "Checked & Approved"));
    $wrapper.find(".pos-recon-investigate-filtered").on("click", () => pos_recon_review_filtered(frm, data, "Needs Investigation"));
}


function pos_recon_update_selected_summary($wrapper) {
    const selected = $wrapper.find(".pos-recon-row-check:checked");
    const summary = $wrapper.find(".pos-recon-selected-summary");
    if (!selected.length) {
        summary.hide();
        return;
    }
    let gross = 0, commission = 0, vat = 0;
    selected.each(function () {
        gross += Number($(this).attr("data-gross") || 0);
        commission += Number($(this).attr("data-commission") || 0);
        vat += Number($(this).attr("data-vat") || 0);
    });
    summary.find(".pos-recon-selected-count").text(selected.length);
    summary.find(".pos-recon-selected-gross").text(pos_recon_money(gross));
    summary.find(".pos-recon-selected-commission").text(pos_recon_money(commission));
    summary.find(".pos-recon-selected-vat").text(pos_recon_money(vat));
    summary.find(".pos-recon-selected-net").text(pos_recon_money(gross - commission - vat));
    summary.show();
}

function pos_recon_selected_records($wrapper) {
    return $wrapper.find(".pos-recon-row-check:checked").map(function () {
        return $(this).attr("data-record");
    }).get().filter(Boolean);
}


function pos_recon_require_settlement_filter(frm) {
    const settlement = (frm.__pos_recon_review.results.settlement_number || "").trim();
    if (!settlement) {
        frappe.msgprint(__("Settlement Number is required before Finance review actions. This keeps bulk approval tied to a bank settlement group."));
        return false;
    }
    return true;
}


function pos_recon_review_selected(frm, $wrapper, decision) {
    if (!pos_recon_require_settlement_filter(frm)) return;
    const records = pos_recon_selected_records($wrapper);
    if (!records.length) {
        frappe.msgprint(__("Select at least one Bank Only transaction."));
        return;
    }
    pos_recon_prompt_review(decision, records.length, null, (note) => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.finance_review_selected",
            args: { record_names: records, decision: decision, note: note },
            freeze: true,
            freeze_message: __("Updating Finance review..."),
        }).then(() => frm.reload_doc());
    });
}


function pos_recon_reset_selected(frm, $wrapper) {
    if (!pos_recon_require_settlement_filter(frm)) return;
    const records = pos_recon_selected_records($wrapper);
    if (!records.length) {
        frappe.msgprint(__("Select at least one Bank Only transaction."));
        return;
    }
    frappe.confirm(__("Reset Finance review for {0} selected transactions?", [records.length]), () => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.finance_review_reset",
            args: { record_names: records },
            freeze: true,
            freeze_message: __("Resetting Finance review..."),
        }).then(() => frm.reload_doc());
    });
}


function pos_recon_review_filtered(frm, data, decision) {
    if (!pos_recon_require_settlement_filter(frm)) return;
    const state = frm.__pos_recon_review.results;
    const summary = data.settlement_summary || {};
    const count = cint(summary.transaction_count || data.total || 0);
    if (!count) {
        frappe.msgprint(__("No Bank Only transactions match the current filters."));
        return;
    }

    const detail = __("{0} transactions, gross {1}.", [count, pos_recon_money(summary.gross_amount || 0)]);
    pos_recon_prompt_review(decision, count, detail, (note) => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.finance_review_filtered",
            args: {
                run_name: frm.doc.name,
                settlement_number: state.settlement_number,
                from_date: state.from_date,
                to_date: state.to_date,
                settlement_date: state.settlement_date,
                pos_profile: state.pos_profile,
                terminal_id: state.terminal_id,
                card_type: state.card_type,
                finance_review_status: state.finance_review_status,
                before_integration: state.before_integration,
                search: state.search,
                decision: decision,
                note: note,
            },
            freeze: true,
            freeze_message: __("Updating filtered Finance review..."),
        }).then(() => frm.reload_doc());
    });
}


function pos_recon_prompt_review(decision, count, detail, callback) {
    const approved = decision === "Checked & Approved";
    frappe.prompt(
        [{
            fieldname: "note",
            fieldtype: "Small Text",
            label: __("Finance Review Note"),
            reqd: !approved,
            default: approved ? __("Finance checked and approved against books") : "",
        }],
        (values) => {
            const extra = detail ? `<br>${pos_recon_escape(detail)}` : "";
            const message = approved
                ? __("Mark {0} Bank Only transactions as Checked & Approved?", [count]) + extra
                : __("Mark {0} Bank Only transactions as Needs Investigation?", [count]) + extra;
            frappe.confirm(message, () => callback(values.note || ""));
        },
        __("Finance Review"),
        approved ? __("Continue") : __("Flag")
    );
}


function pos_recon_bind_search($wrapper, callback) {
    let timer = null;
    $wrapper.find(".pos-recon-search").on("input", function () {
        const value = $(this).val() || "";
        clearTimeout(timer);
        timer = setTimeout(() => callback(value.trim()), 350);
    });
}


function pos_recon_bind_pager($wrapper, start, page_length, total, callback) {
    $wrapper.find('[data-page-action="prev"]').on("click", () => callback(Math.max(start - page_length, 0)));
    $wrapper.find('[data-page-action="next"]').on("click", () => {
        if (start + page_length < total) callback(start + page_length);
    });
}


function pos_recon_bind_doc_links($wrapper) {
    $wrapper.find(".pos-recon-doc-link").on("click", function (event) {
        event.preventDefault();
        const doctype = $(this).attr("data-doctype");
        const name = $(this).attr("data-name");
        if (doctype && name) frappe.set_route("Form", doctype, name);
    });
}


function pos_recon_doc_link(doctype, name) {
    return `<a href="#" class="pos-recon-doc-link" data-doctype="${pos_recon_escape(doctype)}" data-name="${pos_recon_escape(name)}">${pos_recon_escape(name)}</a>`;
}


function pos_recon_render_loading($wrapper) {
    $wrapper.html(`<div class="text-muted small" style="padding:12px 0;">${__("Loading reconciliation data...")}</div>`);
}


function pos_recon_total_results(frm) {
    return [frm.doc.matching_count, frm.doc.discrepancy_count, frm.doc.bank_only_count, frm.doc.alhamrani_only_count]
        .reduce((total, value) => total + cint(value || 0), 0);
}


function pos_recon_range_text(start, row_count, total) {
    if (!total) return __("0 records");
    return __("{0}-{1} of {2}", [start + 1, start + row_count, total]);
}


function pos_recon_pager(start, page_length, total) {
    const prev_disabled = start <= 0 ? "disabled" : "";
    const next_disabled = start + page_length >= total ? "disabled" : "";
    return `<div class="pos-recon-pager">
        <button class="btn btn-xs btn-default" data-page-action="prev" ${prev_disabled}>${__("Previous")}</button>
        <button class="btn btn-xs btn-default" data-page-action="next" ${next_disabled}>${__("Next")}</button>
    </div>`;
}


function pos_recon_money(value) {
    const number = Number(value || 0);
    return `${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} SAR`;
}


function pos_recon_status_pill(status) {
    const value = status || "";
    const color = { "Matching": "green", "Discrepancy": "orange", "Bank Only": "red", "Alhamrani Only": "red" }[value] || "gray";
    return `<span class="indicator-pill ${color}">${pos_recon_escape(value || "—")}</span>`;
}


function pos_recon_resolution_pill(status) {
    const value = status || "";
    const color = { "Auto Cleared": "green", "Pending": "orange", "Manually Cleared": "blue" }[value] || "gray";
    return `<span class="indicator-pill ${color}">${pos_recon_escape(value || "—")}</span>`;
}


function pos_recon_finance_pill(status) {
    const value = status || "";
    const color = {
        "Checked & Approved": "green",
        "Needs Investigation": "orange",
        "Pending Review": "gray",
        "Not Required": "gray",
    }[value] || "gray";
    return `<span class="indicator-pill ${color}">${pos_recon_escape(value || "—")}</span>`;
}


function pos_recon_accounting_pill(status) {
    const value = status || "Not Eligible";
    const color = {
        "Posted": "green",
        "Pending Accounting": "orange",
        "No Charges": "blue",
        "Posted - Review Required": "red",
        "Not Eligible": "gray",
    }[value] || "gray";
    return `<span class="indicator-pill ${color}">${pos_recon_escape(value)}</span>`;
}


function pos_recon_escape(value) {
    return $("<div>").text(value === null || value === undefined ? "" : String(value)).html();
}


function pos_recon_styles() {
    return `<style>
        .pos-recon-panel { border:1px solid var(--border-color); border-radius:var(--border-radius-md); padding:12px; margin-bottom:12px; background:var(--card-bg); }
        .pos-recon-panel-head,.pos-recon-toolbar,.pos-recon-pager,.pos-recon-finance-actions { display:flex; align-items:center; justify-content:space-between; gap:10px; }
        .pos-recon-title { font-weight:600; margin-bottom:2px; }
        .pos-recon-toolbar { margin:10px 0; }
        .pos-recon-toolbar .pos-recon-search { max-width:360px; }
        .pos-recon-table-wrap { overflow-x:auto; border-radius:var(--border-radius-sm); }
        .pos-recon-table { margin-bottom:0; min-width:920px; }
        .pos-recon-results-table { min-width:1550px; }
        .pos-recon-table th,.pos-recon-table td { white-space:nowrap; vertical-align:middle !important; font-size:12px; }
        .pos-recon-result-filters { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0 4px; }
        .pos-recon-result-filters .badge { margin-left:4px; }
        .pos-recon-pager { justify-content:flex-end; margin-top:10px; }
        .pos-recon-bank-review { border:1px solid var(--border-color); border-radius:var(--border-radius-sm); padding:10px; margin:10px 0; }
        .pos-recon-bank-filter-grid { display:grid; grid-template-columns:repeat(4,minmax(145px,1fr)); gap:8px; align-items:end; }
        .pos-recon-bank-filter-grid label { font-size:11px; color:var(--text-muted); margin-bottom:3px; display:block; }
        .pos-recon-filter-actions { display:flex; gap:5px; }
        .pos-recon-selected-summary { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr)); gap:8px; margin:10px 0; }
        .pos-recon-selected-summary div { background:var(--subtle-fg); border-radius:var(--border-radius-sm); padding:8px; display:flex; flex-direction:column; gap:2px; }
        .pos-recon-selected-summary b { font-size:11px; color:var(--text-muted); }
        .pos-recon-settlement-summary { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:8px; margin-top:10px; }
        .pos-recon-settlement-summary div { background:var(--subtle-fg); border-radius:var(--border-radius-sm); padding:8px; display:flex; flex-direction:column; gap:2px; }
        .pos-recon-settlement-summary b { font-size:11px; color:var(--text-muted); }
        .pos-recon-settlement-warning { margin:8px 0 0; padding:8px; }
        .pos-recon-summary-hint { margin-top:8px; }
        .pos-recon-finance-actions { justify-content:flex-start; flex-wrap:wrap; margin-top:10px; }
        .pos-recon-action-spacer { flex:1; }
        @media (max-width:1100px) { .pos-recon-bank-filter-grid { grid-template-columns:repeat(2,minmax(140px,1fr)); } .pos-recon-settlement-summary { grid-template-columns:repeat(2,minmax(120px,1fr)); } }
    </style>`;
}

function pos_recon_open_accounting_dialog(frm) {
    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_accounting_options",
        args: { run_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Checking accounting eligibility..."),
    }).then((r) => {
        const options = r.message || {};
        if (!cint(options.enabled)) {
            frappe.msgprint({
                title: __("POS Accounting Posting Disabled"),
                indicator: "orange",
                message: __("Enable POS Accounting Posting and configure the accounts in POS Reconciliation Settings first."),
            });
            return;
        }
        if (!cint(options.pending_count || 0)) {
            frappe.msgprint(__("There are no confirmed transactions pending accounting in this reconciliation run."));
            return;
        }

        const settlement_options = [""].concat(options.settlement_numbers || []).join("\n");
        const consolidate_text = cint(options.consolidate_pos_profiles)
            ? __("Multiple POS Profiles in the same settlement/date will be consolidated into one Journal Entry. Commission debit lines remain split by POS Profile Cost Center.")
            : __("A separate Journal Entry will be created for each POS Profile.");

        frappe.prompt(
            [
                {
                    fieldname: "settlement_number",
                    fieldtype: "Select",
                    label: __("Settlement Number"),
                    options: settlement_options,
                    reqd: 1,
                },
                {
                    fieldname: "settlement_date",
                    fieldtype: "Date",
                    label: __("Settlement Date"),
                    description: __("Required only when the same Settlement Number exists on more than one settlement date."),
                },
                {
                    fieldname: "pos_profile",
                    fieldtype: "Link",
                    options: "POS Profile",
                    label: __("POS Profile"),
                    description: __("Optional. Leave blank to include all eligible POS Profiles."),
                },
                {
                    fieldname: "posting_note",
                    fieldtype: "HTML",
                    options: `<div class="text-muted small">${consolidate_text}<br>${__("Posting Date will be the bank Settlement Date. Only Matching or Manually Cleared transactions are eligible.")}</div>`,
                },
            ],
            (values) => {
                frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_accounting_preview_for_run",
                    args: {
                        run_name: frm.doc.name,
                        settlement_number: values.settlement_number,
                        settlement_date: values.settlement_date || null,
                        pos_profile: values.pos_profile || null,
                    },
                    freeze: true,
                    freeze_message: __("Preparing accounting preview..."),
                }).then((preview_response) => {
                    const preview = preview_response.message || {};
                    const message = __(
                        "Create {0} Journal Entry/Entries for {1} confirmed transactions?<br><br>POS Profiles: {2}<br>Bank Commission: {3}<br>VAT: {4}<br>Total Bank Credit: {5}",
                        [
                            preview.journal_entry_count || 0,
                            preview.transaction_count || 0,
                            preview.pos_profile_count || 0,
                            pos_recon_money(preview.commission),
                            pos_recon_money(preview.vat),
                            pos_recon_money(preview.total),
                        ]
                    );
                    frappe.confirm(message, () => {
                        frappe.call({
                            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.create_accounting_entries",
                            args: {
                                run_name: frm.doc.name,
                                settlement_number: values.settlement_number,
                                settlement_date: values.settlement_date || null,
                                pos_profile: values.pos_profile || null,
                            },
                            freeze: true,
                            freeze_message: __("Creating and submitting Journal Entries..."),
                        }).then((post_response) => {
                            const result = post_response.message || {};
                            const rows = (result.postings || []).map((row) =>
                                `${pos_recon_escape(row.posting)} â†’ ${pos_recon_escape(row.journal_entry)}`
                            ).join("<br>");
                            frappe.msgprint({
                                title: __("POS Accounting Posted"),
                                indicator: "green",
                                message: __(
                                    "Posted {0} transactions in {1} Journal Entry/Entries.<br>Commission: {2}<br>VAT: {3}<br><br>{4}",
                                    [
                                        result.transaction_count || 0,
                                        result.posting_count || 0,
                                        pos_recon_money(result.commission),
                                        pos_recon_money(result.vat),
                                        rows,
                                    ]
                                ),
                            });
                            frm.reload_doc();
                        });
                    });
                });
            },
            __("Create POS Accounting Entries"),
            __("Preview")
        );
    });
}
