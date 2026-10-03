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
                __("This run is completed. Review the two source lists and reconciliation results below. Use Re-run Reconciliation if source transactions have changed."),
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
                            frm.reload_doc();
                            frappe.msgprint({
                                title: __("Reconciliation Completed"),
                                indicator: result.pending_count ? "orange" : "green",
                                message: __(
                                    "Matching: {0}<br>Discrepancies: {1}<br>Bank Only: {2}<br>Alhamrani Only: {3}<br>Manually Cleared: {4}<br>Pending: {5}",
                                    [
                                        result.matching_count || 0,
                                        result.discrepancy_count || 0,
                                        result.bank_only_count || 0,
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

        frm.add_custom_button(__("Pending Exceptions"), () => {
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

        frm.add_custom_button(__("Pending Bank Only"), () => {
            frappe.set_route("List", "POS Reconciliation Record", {
                run: frm.doc.name,
                match_status: "Bank Only",
                resolution_status: "Pending",
            });
        }, __("View"));

        frm.add_custom_button(__("Pending Alhamrani Only"), () => {
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

        if (frm.doc.status === "Completed") {
            pos_recon_setup_review(frm);
        }
    },
});


function pos_recon_setup_review(frm) {
    if (!frm.__pos_recon_review) {
        frm.__pos_recon_review = {
            bank: { start: 0, search: "" },
            alhamrani: { start: 0, search: "" },
            results: { start: 0, search: "", status: "All" },
        };
    }

    pos_recon_load_source(frm, "bank");
    pos_recon_load_source(frm, "alhamrani");
    pos_recon_load_results(frm);
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
        const data = r.message || {};
        pos_recon_render_source(frm, source, field.$wrapper, data);
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
        },
    }).then((r) => {
        const data = r.message || {};
        pos_recon_render_results(frm, field.$wrapper, data);
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
                <input
                    type="text"
                    class="form-control input-xs pos-recon-search"
                    placeholder="${__("Search reference, terminal, profile or status")}"
                    value="${pos_recon_escape(state.search)}"
                >
                <span class="text-muted small">${pos_recon_range_text(start, rows.length, total)}</span>
            </div>

            <div class="pos-recon-table-wrap">
                <table class="table table-bordered table-hover pos-recon-table">
                    <thead>
                        <tr>
                            <th>${__("Reference")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Time")}</th>
                            <th>${__("Terminal ID")}</th>
                            <th>${__("RRN")}</th>
                            <th>${__("Auth")}</th>
                            <th>${__("Type")}</th>
                            <th class="text-right">${__("Amount")}</th>
                            <th>${__("Card")}</th>
                            <th>${__("Result")}</th>
                        </tr>
                    </thead>
                    <tbody>${body}</tbody>
                </table>
            </div>

            ${pos_recon_pager(start, page_length, total)}
        </div>
    `);

    pos_recon_bind_doc_links($wrapper);

    $wrapper.find(".pos-recon-open-list").on("click", () => {
        frappe.set_route("List", doctype);
    });

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

    const statuses = [
        ["All", __("All"), pos_recon_total_results(frm)],
        ["Matching", __("Matching"), cint(frm.doc.matching_count || 0)],
        ["Discrepancy", __("Discrepancies"), cint(frm.doc.discrepancy_count || 0)],
        ["Bank Only", __("Bank Only"), cint(frm.doc.bank_only_count || 0)],
        ["Alhamrani Only", __("Alhamrani Only"), cint(frm.doc.alhamrani_only_count || 0)],
        ["Pending", __("Pending"), cint(frm.doc.pending_count || 0)],
        ["Manually Cleared", __("Manually Cleared"), cint(frm.doc.manually_cleared_count || 0)],
    ];

    const filter_buttons = statuses.map(([value, label, count]) => `
        <button
            class="btn btn-xs ${state.status === value ? "btn-primary" : "btn-default"} pos-recon-status-filter"
            data-status="${pos_recon_escape(value)}"
        >${label} <span class="badge">${count}</span></button>
    `).join("");

    const body = rows.length
        ? rows.map((row) => {
            const details = [
                row.discrepancy_fields || "",
                row.before_integration ? __("Before Integration") : "",
                row.manual_clearance_reason || "",
            ].filter(Boolean).join(" · ");

            return `
                <tr>
                    <td>${row.bank_transaction ? pos_recon_doc_link("Bank POS Transaction", row.bank_transaction) : "—"}</td>
                    <td>${row.alhamrani_transaction ? pos_recon_doc_link("Alhamrani Transaction", row.alhamrani_transaction) : "—"}</td>
                    <td>${pos_recon_escape(row.transaction_date)}</td>
                    <td>${pos_recon_escape(row.terminal_id)}</td>
                    <td>${pos_recon_status_pill(row.match_status)}</td>
                    <td class="text-right">${pos_recon_money(row.bank_amount)}</td>
                    <td class="text-right">${pos_recon_money(row.alhamrani_amount)}</td>
                    <td class="text-right">${pos_recon_money(row.amount_difference)}</td>
                    <td>${pos_recon_escape(details || "—")}</td>
                    <td>${pos_recon_resolution_pill(row.resolution_status)}</td>
                </tr>
            `;
        }).join("")
        : `<tr><td colspan="10" class="text-muted text-center">${__("No reconciliation records found")}</td></tr>`;

    $wrapper.html(`
        ${pos_recon_styles()}
        <div class="pos-recon-panel">
            <div class="pos-recon-panel-head">
                <div>
                    <div class="pos-recon-title">${__("Reconciliation Results")}</div>
                    <div class="text-muted small">
                        ${__("The four-field key identifies the same transaction. Amount, card, date, time and masked PAN are secondary validation fields.")}
                    </div>
                </div>
                <button class="btn btn-xs btn-default pos-recon-open-results">${__("Open Full List")}</button>
            </div>

            <div class="pos-recon-result-filters">${filter_buttons}</div>

            <div class="pos-recon-toolbar">
                <input
                    type="text"
                    class="form-control input-xs pos-recon-search"
                    placeholder="${__("Search transaction, terminal, profile, status or discrepancy")}"
                    value="${pos_recon_escape(state.search)}"
                >
                <span class="text-muted small">${pos_recon_range_text(start, rows.length, total)}</span>
            </div>

            <div class="pos-recon-table-wrap">
                <table class="table table-bordered table-hover pos-recon-table">
                    <thead>
                        <tr>
                            <th>${__("Bank Transaction")}</th>
                            <th>${__("Alhamrani Transaction")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Terminal ID")}</th>
                            <th>${__("Status")}</th>
                            <th class="text-right">${__("Bank Amount")}</th>
                            <th class="text-right">${__("Alhamrani Amount")}</th>
                            <th class="text-right">${__("Difference")}</th>
                            <th>${__("Discrepancy / Note")}</th>
                            <th>${__("Resolution")}</th>
                        </tr>
                    </thead>
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


function pos_recon_bind_search($wrapper, callback) {
    let timer = null;
    $wrapper.find(".pos-recon-search").on("input", function () {
        const value = $(this).val() || "";
        clearTimeout(timer);
        timer = setTimeout(() => callback(value.trim()), 350);
    });
}


function pos_recon_bind_pager($wrapper, start, page_length, total, callback) {
    $wrapper.find('[data-page-action="prev"]').on("click", () => {
        callback(Math.max(start - page_length, 0));
    });
    $wrapper.find('[data-page-action="next"]').on("click", () => {
        if (start + page_length < total) {
            callback(start + page_length);
        }
    });
}


function pos_recon_bind_doc_links($wrapper) {
    $wrapper.find(".pos-recon-doc-link").on("click", function (event) {
        event.preventDefault();
        const doctype = $(this).attr("data-doctype");
        const name = $(this).attr("data-name");
        if (doctype && name) {
            frappe.set_route("Form", doctype, name);
        }
    });
}


function pos_recon_doc_link(doctype, name) {
    return `<a href="#" class="pos-recon-doc-link" data-doctype="${pos_recon_escape(doctype)}" data-name="${pos_recon_escape(name)}">${pos_recon_escape(name)}</a>`;
}


function pos_recon_render_loading($wrapper) {
    $wrapper.html(`
        <div class="text-muted small" style="padding: 12px 0;">
            ${__("Loading reconciliation data...")}
        </div>
    `);
}


function pos_recon_total_results(frm) {
    return [
        frm.doc.matching_count,
        frm.doc.discrepancy_count,
        frm.doc.bank_only_count,
        frm.doc.alhamrani_only_count,
    ].reduce((total, value) => total + cint(value || 0), 0);
}


function pos_recon_range_text(start, row_count, total) {
    if (!total) {
        return __("0 records");
    }
    return __("{0}-{1} of {2}", [start + 1, start + row_count, total]);
}


function pos_recon_pager(start, page_length, total) {
    const prev_disabled = start <= 0 ? "disabled" : "";
    const next_disabled = start + page_length >= total ? "disabled" : "";
    return `
        <div class="pos-recon-pager">
            <button class="btn btn-xs btn-default" data-page-action="prev" ${prev_disabled}>${__("Previous")}</button>
            <button class="btn btn-xs btn-default" data-page-action="next" ${next_disabled}>${__("Next")}</button>
        </div>
    `;
}


function pos_recon_money(value) {
    const number = Number(value || 0);
    return `${number.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })} SAR`;
}


function pos_recon_status_pill(status) {
    const value = status || "";
    const color = {
        "Matching": "green",
        "Discrepancy": "orange",
        "Bank Only": "red",
        "Alhamrani Only": "red",
    }[value] || "gray";

    return `<span class="indicator-pill ${color}">${pos_recon_escape(value || "—")}</span>`;
}


function pos_recon_resolution_pill(status) {
    const value = status || "";
    const color = {
        "Auto Cleared": "green",
        "Pending": "orange",
        "Manually Cleared": "blue",
    }[value] || "gray";

    return `<span class="indicator-pill ${color}">${pos_recon_escape(value || "—")}</span>`;
}


function pos_recon_escape(value) {
    return $("<div>").text(value === null || value === undefined ? "" : String(value)).html();
}


function pos_recon_styles() {
    return `
        <style>
            .pos-recon-panel {
                border: 1px solid var(--border-color);
                border-radius: var(--border-radius-md);
                padding: 12px;
                margin-bottom: 12px;
                background: var(--card-bg);
            }
            .pos-recon-panel-head,
            .pos-recon-toolbar,
            .pos-recon-pager {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
            }
            .pos-recon-title {
                font-weight: 600;
                margin-bottom: 2px;
            }
            .pos-recon-toolbar {
                margin: 10px 0;
            }
            .pos-recon-toolbar .pos-recon-search {
                max-width: 360px;
            }
            .pos-recon-table-wrap {
                overflow-x: auto;
                border-radius: var(--border-radius-sm);
            }
            .pos-recon-table {
                margin-bottom: 0;
                min-width: 920px;
            }
            .pos-recon-table th,
            .pos-recon-table td {
                white-space: nowrap;
                vertical-align: middle !important;
                font-size: 12px;
            }
            .pos-recon-result-filters {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                margin: 12px 0 4px;
            }
            .pos-recon-result-filters .badge {
                margin-left: 4px;
            }
            .pos-recon-pager {
                justify-content: flex-end;
                margin-top: 10px;
            }
        </style>
    `;
}
