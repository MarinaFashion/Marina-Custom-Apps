const POS_RECON_PAGE_LENGTH = 25;

frappe.ui.form.on("POS Reconciliation Run", {
    refresh(frm) {
        if (frm.is_new()) return;

        const lifecycle = frm.doc.status || "Draft";
        const execution = frm.doc.execution_status || "Idle";
        const has_results = Boolean(frm.doc.last_reconciled_on);
        const period_locked = lifecycle === "Closed";

        ["from_date", "to_date", "pos_profile", "card_type"].forEach((fieldname) => {
            frm.set_df_property(fieldname, "read_only", period_locked ? 1 : 0);
        });

        if (lifecycle === "Draft") {
            frm.set_intro(__("This reconciliation period has not been run yet."), "blue");
        } else if (lifecycle === "Open") {
            frm.set_intro(__("This period is Open. Import late Bank data and re-run the same period until Finance decides the month is complete."), "green");
        } else {
            frm.set_intro(__("This period is Closed. Reopen it if late source data must be processed."), "orange");
        }

        if (lifecycle !== "Closed" && execution !== "Running" && !frm.is_dirty()) {
            const label = has_results ? __("Re-run Reconciliation") : __("Run Reconciliation");
            const btn = frm.add_custom_button(label, () => {
                frappe.confirm(
                    __("Reconcile all currently available transactions dated inside this period?"),
                    () => frappe.call({
                        method:"marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.run_reconciliation",
                        args:{run_name:frm.doc.name},freeze:true,freeze_message:__("Reconciling POS transactions...")
                    }).then(() => frm.reload_doc())
                );
            });
            btn.addClass("btn-primary");
        }

        if (lifecycle === "Open" && has_results && execution !== "Running") {
            frm.add_custom_button(__("Close Reconciliation"), () => pos_recon_close_run(frm));
        }
        if (lifecycle === "Closed") {
            frm.add_custom_button(__("Reopen Reconciliation"), () => pos_recon_reopen_run(frm));
        }

        frm.add_custom_button(__("All Records"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name}), __("View"));
        frm.add_custom_button(__("All Pending"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,resolution_status:"Pending"}), __("View"));
        frm.add_custom_button(__("Matching"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,match_status:"Matching"}), __("View"));
        frm.add_custom_button(__("Discrepancies"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,match_status:"Discrepancy"}), __("View"));
        frm.add_custom_button(__("Bank Pending"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,match_status:"Bank Only",resolution_status:"Pending"}), __("View"));
        frm.add_custom_button(__("Marina Pending"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,match_status:"Alhamrani Only",resolution_status:"Pending"}), __("View"));
        frm.add_custom_button(__("Manually Cleared"), () => frappe.set_route("List","POS Reconciliation Record",{run:frm.doc.name,resolution_status:"Manually Cleared"}), __("View"));
        frm.add_custom_button(__("Reconciliation Settings"), () => frappe.set_route("Form","POS Reconciliation Settings","POS Reconciliation Settings"), __("View"));

        if (has_results && ["Open","Closed"].includes(lifecycle)) {
            frm.add_custom_button(__("Accounting Postings"), () => frappe.set_route("List","POS Accounting Posting",{source_run:frm.doc.name}), __("Accounting"));
            if (lifecycle === "Open") {
                frm.add_custom_button(__("Create Journal Entries"), () => pos_recon_open_accounting_dialog(frm), __("Accounting"));
            }
            pos_recon_setup_review(frm);
        }
    },
});

function pos_recon_close_run(frm) {
    frappe.prompt(
        [{fieldname:"closing_note",fieldtype:"Small Text",label:__("Closing Note"),
          description:__("Optional. Closing means Finance considers this period complete for normal reconciliation. It can be reopened later for late Bank data.")}],
        (values) => frappe.confirm(
            __("Close this period?<br><br>Period: {0} to {1}<br>Bank Transactions: {2}<br>Pending Exceptions: {3}<br>Last Reconciled: {4}",[
                frm.doc.from_date||"",frm.doc.to_date||"",cint(frm.doc.bank_transaction_count||0),
                cint(frm.doc.pending_count||0),frm.doc.last_reconciled_on||""
            ]),
            () => frappe.call({
                method:"marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.close_reconciliation",
                args:{run_name:frm.doc.name,note:values.closing_note||""},freeze:true,
                freeze_message:__("Closing reconciliation period...")
            }).then(() => frm.reload_doc())
        ),
        __("Close Reconciliation"),__("Continue")
    );
}

function pos_recon_reopen_run(frm) {
    frappe.prompt(
        [{fieldname:"reopen_reason",fieldtype:"Small Text",label:__("Reopen Reason"),reqd:1,
          description:__("Explain why the closed period must be reopened, for example late Bank settlement data.")}],
        (values) => frappe.call({
            method:"marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.reopen_reconciliation",
            args:{run_name:frm.doc.name,reason:values.reopen_reason},freeze:true,
            freeze_message:__("Reopening reconciliation period...")
        }).then(() => frm.reload_doc()),
        __("Reopen Reconciliation"),__("Reopen")
    );
}
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
                accounting_status: "",
                ledger_posting_status: "",
                before_integration: "All",
                status_counts: {},
                options: { settlement_numbers: [], pos_profiles: [], terminal_ids: [], card_types: [],
                    finance_review_statuses: [], accounting_statuses: [], ledger_posting_statuses: [], before_integration_values: [] },
            },
        };
    }

    pos_recon_load_filter_options(frm).then(() => pos_recon_load_results(frm));
}


function pos_recon_filter_args(frm, values) {
    const s=frm.__pos_recon_review.results, v=values||s;
    return {
        run_name:frm.doc.name,status:v.status||"All",from_date:v.from_date||"",to_date:v.to_date||"",
        settlement_number:v.settlement_number||"",settlement_date:v.settlement_date||"",pos_profile:v.pos_profile||"",
        terminal_id:v.terminal_id||"",card_type:v.card_type||"",finance_review_status:v.finance_review_status||"",
        accounting_status:v.accounting_status||"",ledger_posting_status:v.ledger_posting_status||"",
        before_integration:v.before_integration===undefined?"All":v.before_integration
    };
}

function pos_recon_available(values,current) {
    return !current || (values||[]).map(String).includes(String(current));
}

function pos_recon_reconcile_state(state,o) {
    let changed=false;
    [["settlement_number","settlement_numbers"],["pos_profile","pos_profiles"],["terminal_id","terminal_ids"],
     ["card_type","card_types"],["finance_review_status","finance_review_statuses"],
     ["accounting_status","accounting_statuses"],["ledger_posting_status","ledger_posting_statuses"]]
    .forEach(([f,k]) => {
        if(!pos_recon_available(o[k],state[f])){
            state[f]="";
            changed=true;
        }
    });
    if(state.before_integration!=="All" && !pos_recon_available(o.before_integration_values,state.before_integration)){
        state.before_integration="All";
        changed=true;
    }
    return changed;
}

function pos_recon_load_filter_options(frm, values=null, update_counts=true, reconcile=true) {
    const state=frm.__pos_recon_review.results;
    return frappe.call({
        method:"marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_review_filter_options",
        args:pos_recon_filter_args(frm,values)
    }).then((r)=>{
        const o=r.message||{};
        state.options=o;
        if(update_counts) state.status_counts=o.status_counts||{};

        if(reconcile && !values && pos_recon_reconcile_state(state,o)){
            // One or more old selections became invalid after a tab/filter change.
            // Recalculate once with the cleaned state so dropdown choices and
            // status counts correspond to the exact state used by the result table.
            return pos_recon_load_filter_options(frm,null,update_counts,false);
        }
        return o;
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
            accounting_status: state.accounting_status,
            ledger_posting_status: state.ledger_posting_status,
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
    const can_review = is_bank_only && frm.doc.status === "Open";
    const counts = state.status_counts || {};
    const statuses = [
        ["All",__("All"),cint(counts["All"]||0)],["Matching",__("Matching"),cint(counts["Matching"]||0)],
        ["Discrepancy",__("Discrepancies"),cint(counts["Discrepancy"]||0)],["Bank Pending",__("Bank Pending"),cint(counts["Bank Pending"]||0)],
        ["Marina Pending",__("Marina Pending"),cint(counts["Marina Pending"]||0)],["Manually Cleared",__("Manually Cleared"),cint(counts["Manually Cleared"]||0)],
        ["All Pending",__("All Pending"),cint(counts["All Pending"]||0)],
    ];

    const filter_buttons = statuses.map(([value, label, count]) => `
        <button class="btn btn-xs ${state.status === value ? "btn-primary" : "btn-default"} pos-recon-status-filter"
            data-status="${pos_recon_escape(value)}">${label} <span class="badge">${count}</span></button>
    `).join("");

    const review_filters = pos_recon_result_filters(state, state.options || {}, is_bank_only, data.filtered_summary || data.settlement_summary || {}, can_review);
    const checkbox_head = can_review ? `<th style="width:32px"><input type="checkbox" class="pos-recon-select-page"></th>` : "";

    const body = rows.length
        ? rows.map((row) => {
            const details = [
                row.discrepancy_fields || "",
                row.before_integration ? __("Before Integration") : "",
                row.finance_review_note || "",
                row.manual_clearance_reason || "",
            ].filter(Boolean).join(" · ");
            const actionable = can_review && row.resolution_status === "Pending";
            const checkbox = can_review
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
                    <td>${pos_recon_accounting_pill(row.accounting_status)}</td>
                    <td>${pos_recon_escape(details || "—")}</td>
                    <td>${pos_recon_resolution_pill(row.resolution_status)}</td>
                </tr>
            `;
        }).join("")
        : `<tr><td colspan="${can_review ? 16 : 15}" class="text-muted text-center">${__("No reconciliation records found")}</td></tr>`;

    const selected_summary = can_review ? `
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
        if (state.status !== "Bank Pending") { state.finance_review_status=""; state.before_integration="All"; }
        state.start=0;
        pos_recon_load_filter_options(frm).then(()=>pos_recon_load_results(frm));
    });

    pos_recon_bind_result_filters(frm,$wrapper,data,is_bank_only,can_review);

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


function pos_recon_result_filters(state, options, is_bank_only, summary, can_review) {
    summary=summary||{};
    const summary_html=`
      <div class="pos-recon-summary-panel">
        <div class="pos-recon-summary-title"><div><div class="pos-recon-summary-heading">${__("Filtered Summary")}</div>
          <div class="text-muted small">${__("Totals follow the selected status and all applied filters.")}</div></div>
          <span class="indicator-pill blue">${cint(summary.transaction_count||0)} ${__("Transactions")}</span></div>
        <div class="pos-recon-summary-group-label">${__("Financial Totals")}</div>
        <div class="pos-recon-settlement-summary pos-recon-summary-financial">
          <div><b>${__("Bank Gross")}</b><span>${pos_recon_money(summary.gross_amount)}</span></div>
          <div><b>${__("Marina Amount")}</b><span>${pos_recon_money(summary.marina_amount)}</span></div>
          <div><b>${__("Expected Net")}</b><span>${pos_recon_money(summary.expected_net)}</span></div>
          <div><b>${__("Commission")}</b><span>${pos_recon_money(summary.commission)}</span></div>
          <div><b>${__("Commission %")}</b><span>${Number(summary.commission_pct||0).toFixed(2)}%</span></div>
          <div><b>${__("VAT")}</b><span>${pos_recon_money(summary.vat)}</span></div>
          <div><b>${__("VAT %")}</b><span>${Number(summary.vat_pct||0).toFixed(2)}%</span></div>
        </div>
        <div class="pos-recon-summary-group-label">${__("Finance & Accounting Status")}</div>
        <div class="pos-recon-settlement-summary">
          <div><b>${__("Accounting Eligible")}</b><span>${cint(summary.accounting_eligible_count||0)}</span></div>
          <div><b>${__("Pending Accounting")}</b><span>${cint(summary.pending_accounting_count||0)}</span></div>
          <div><b>${__("Draft Created")}</b><span>${cint(summary.draft_created_count||0)}</span></div>
          <div><b>${__("Posted to Ledger")}</b><span>${cint(summary.posted_to_ledger_count||0)}</span></div>
          <div><b>${__("No Charges")}</b><span>${cint(summary.no_charges_count||0)}</span></div>
          <div><b>${__("Approved")}</b><span>${cint(summary.approved_count||0)}</span></div>
          <div><b>${__("Needs Investigation")}</b><span>${cint(summary.investigation_count||0)}</span></div>
          <div><b>${__("Pending Review")}</b><span>${cint(summary.pending_review_count||0)}</span></div>
        </div>
      </div>`;

    const finance_fields=is_bank_only?`
      <div><label>${__("Finance Review")}</label><select class="form-control input-xs pos-recon-filter-finance">${pos_recon_select_options(options.finance_review_statuses||[],state.finance_review_status,__("All"))}</select></div>
      <div><label>${__("Before Integration")}</label><select class="form-control input-xs pos-recon-filter-before">
        <option value="All">${__("All")}</option>
        ${(options.before_integration_values||[]).includes("1")?`<option value="1" ${String(state.before_integration)==="1"?"selected":""}>${__("Yes")}</option>`:""}
        ${(options.before_integration_values||[]).includes("0")?`<option value="0" ${String(state.before_integration)==="0"?"selected":""}>${__("No")}</option>`:""}
      </select></div>`:"";

    const ledger_fields=`
      <div><label>${__("Ledger Posting Status")}</label><select class="form-control input-xs pos-recon-filter-ledger">${pos_recon_select_options(options.ledger_posting_statuses||[],state.ledger_posting_status,__("All"))}</select></div>
      <div><label>${__("Accounting Status")}</label><select class="form-control input-xs pos-recon-filter-accounting">${pos_recon_select_options(options.accounting_statuses||[],state.accounting_status,__("All"))}</select></div>`;

    const multiple=cint(summary.settlement_date_count||0)>1||cint(summary.terminal_count||0)>1;
    const disabled=!can_review||multiple||!state.settlement_number?"disabled":"";
    const actions=can_review?`<div class="pos-recon-finance-actions">
      <button class="btn btn-xs btn-primary pos-recon-approve-selected">${__("Checked & Approved – Selected")}</button>
      <button class="btn btn-xs btn-default pos-recon-investigate-selected">${__("Needs Investigation – Selected")}</button>
      <button class="btn btn-xs btn-default pos-recon-reset-selected">${__("Reset Selected")}</button>
      <span class="pos-recon-action-spacer"></span>
      <button class="btn btn-xs btn-primary pos-recon-approve-filtered" ${disabled}>${__("Checked & Approved – All Filtered")}</button>
      <button class="btn btn-xs btn-default pos-recon-investigate-filtered" ${disabled}>${__("Needs Investigation – All Filtered")}</button></div>`:"";

    return `<div class="pos-recon-bank-review">
      <div class="pos-recon-filter-section-title">${__("Filters")}</div>
      <div class="pos-recon-bank-filter-grid">
        <div><label>${__("From Date")}</label><input type="date" class="form-control input-xs pos-recon-filter-from-date" value="${pos_recon_escape(state.from_date)}"></div>
        <div><label>${__("To Date")}</label><input type="date" class="form-control input-xs pos-recon-filter-to-date" value="${pos_recon_escape(state.to_date)}"></div>
        <div><label>${__("Settlement Number")}</label><select class="form-control input-xs pos-recon-filter-settlement">${pos_recon_select_options(options.settlement_numbers||[],state.settlement_number,__("All"))}</select></div>
        <div><label>${__("POS Profile")}</label><select class="form-control input-xs pos-recon-filter-profile">${pos_recon_select_options(options.pos_profiles||[],state.pos_profile,__("All"))}</select></div>
        <div><label>${__("Terminal ID")}</label><select class="form-control input-xs pos-recon-filter-terminal">${pos_recon_select_options(options.terminal_ids||[],state.terminal_id,__("All"))}</select></div>
        <div><label>${__("Card Type")}</label><select class="form-control input-xs pos-recon-filter-card">${pos_recon_select_options(options.card_types||[],state.card_type,__("All"))}</select></div>
        ${ledger_fields}${finance_fields}
        <div class="pos-recon-filter-actions"><button class="btn btn-xs btn-primary pos-recon-apply-bank-filters">${__("Apply Filters")}</button><button class="btn btn-xs btn-default pos-recon-clear-bank-filters">${__("Clear")}</button></div>
      </div>${summary_html}${actions}</div>`;
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


function pos_recon_read_controls($w,is_bank,state){
    return {status:state.status||"All",from_date:$w.find(".pos-recon-filter-from-date").val()||"",
      to_date:$w.find(".pos-recon-filter-to-date").val()||"",settlement_number:$w.find(".pos-recon-filter-settlement").val()||"",
      settlement_date:state.settlement_date||"",pos_profile:$w.find(".pos-recon-filter-profile").val()||"",
      terminal_id:$w.find(".pos-recon-filter-terminal").val()||"",card_type:$w.find(".pos-recon-filter-card").val()||"",
      ledger_posting_status:$w.find(".pos-recon-filter-ledger").val()||"",accounting_status:$w.find(".pos-recon-filter-accounting").val()||"",
      finance_review_status:is_bank?($w.find(".pos-recon-filter-finance").val()||""):"",
      before_integration:is_bank?($w.find(".pos-recon-filter-before").val()||"All"):"All"};
}
function pos_recon_update_select($w,selector,values,current){const $f=$w.find(selector);if($f.length)$f.html(pos_recon_select_options(values||[],current||"",__("All")));}
function pos_recon_update_cascade($w,o,d,is_bank){
    pos_recon_update_select($w,".pos-recon-filter-settlement",o.settlement_numbers,d.settlement_number);
    pos_recon_update_select($w,".pos-recon-filter-profile",o.pos_profiles,d.pos_profile);
    pos_recon_update_select($w,".pos-recon-filter-terminal",o.terminal_ids,d.terminal_id);
    pos_recon_update_select($w,".pos-recon-filter-card",o.card_types,d.card_type);
    pos_recon_update_select($w,".pos-recon-filter-ledger",o.ledger_posting_statuses,d.ledger_posting_status);
    pos_recon_update_select($w,".pos-recon-filter-accounting",o.accounting_statuses,d.accounting_status);
    if(is_bank){
        pos_recon_update_select($w,".pos-recon-filter-finance",o.finance_review_statuses,d.finance_review_status);
        const $before=$w.find(".pos-recon-filter-before");
        if($before.length){
            const values=o.before_integration_values||[];
            const wanted=String(d.before_integration||"All");
            $before.html(
                `<option value="All">${__("All")}</option>` +
                (values.includes("1") ? `<option value="1">${__("Yes")}</option>` : "") +
                (values.includes("0") ? `<option value="0">${__("No")}</option>` : "")
            );
            $before.val((wanted==="All" || values.includes(wanted)) ? wanted : "All");
        }
    }
}

function pos_recon_bind_result_filters(frm,$wrapper,data,is_bank_only,can_review){
    const state=frm.__pos_recon_review.results;let timer=null;
    $wrapper.find(".pos-recon-bank-filter-grid select,.pos-recon-bank-filter-grid input[type='date']").on("change",()=>{
        clearTimeout(timer);timer=setTimeout(()=>{
            const draft=pos_recon_read_controls($wrapper,is_bank_only,state);
            pos_recon_load_filter_options(frm,draft,false,false).then(o=>pos_recon_update_cascade($wrapper,o,draft,is_bank_only));
        },150);
    });
    $wrapper.find(".pos-recon-apply-bank-filters").on("click",()=>{
        Object.assign(state,pos_recon_read_controls($wrapper,is_bank_only,state));state.start=0;
        pos_recon_load_filter_options(frm).then(()=>pos_recon_load_results(frm));
    });
    $wrapper.find(".pos-recon-clear-bank-filters").on("click",()=>{
        Object.assign(state,{from_date:frm.doc.from_date||"",to_date:frm.doc.to_date||"",settlement_number:"",
          settlement_date:"",pos_profile:"",terminal_id:"",card_type:"",finance_review_status:"",
          accounting_status:"",ledger_posting_status:"",before_integration:"All",start:0});
        pos_recon_load_filter_options(frm).then(()=>pos_recon_load_results(frm));
    });
    if(!can_review)return;
    const update=()=>pos_recon_update_selected_summary($wrapper);
    $wrapper.find(".pos-recon-select-page").on("change",function(){$wrapper.find(".pos-recon-row-check").prop("checked",$(this).prop("checked"));update();});
    $wrapper.find(".pos-recon-row-check").on("change",update);
    $wrapper.find(".pos-recon-approve-selected").on("click",()=>pos_recon_review_selected(frm,$wrapper,"Checked & Approved"));
    $wrapper.find(".pos-recon-investigate-selected").on("click",()=>pos_recon_review_selected(frm,$wrapper,"Needs Investigation"));
    $wrapper.find(".pos-recon-reset-selected").on("click",()=>pos_recon_reset_selected(frm,$wrapper));
    $wrapper.find(".pos-recon-approve-filtered").on("click",()=>pos_recon_review_filtered(frm,data,"Checked & Approved"));
    $wrapper.find(".pos-recon-investigate-filtered").on("click",()=>pos_recon_review_filtered(frm,data,"Needs Investigation"));
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
    const summary = data.filtered_summary || data.settlement_summary || {};
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
                accounting_status: state.accounting_status,
                ledger_posting_status: state.ledger_posting_status,
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
        "Draft Created": "blue",
        "Pending Accounting": "orange",
        "No Charges": "blue",
        "Draft - Review Required": "red",
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
        .pos-recon-filter-section-title { font-weight:600; margin:0 0 8px; }
        .pos-recon-summary-panel { margin-top:18px; padding:14px; border:1px solid var(--border-color); border-radius:var(--border-radius-md); background:var(--fg-color); box-shadow:0 1px 2px rgba(0,0,0,.04); }
        .pos-recon-summary-title { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:0 0 12px; padding-bottom:10px; border-bottom:1px solid var(--border-color); }
        .pos-recon-summary-heading { font-size:14px; font-weight:700; }
        .pos-recon-summary-group-label { margin:12px 0 6px; font-size:11px; font-weight:600; color:var(--text-muted); text-transform:uppercase; letter-spacing:.04em; }
        .pos-recon-settlement-summary { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:8px; margin-top:6px; }
        .pos-recon-settlement-summary div { background:var(--subtle-fg); border:1px solid var(--border-color); border-radius:var(--border-radius-sm); padding:10px; display:flex; flex-direction:column; gap:3px; min-height:58px; }
        .pos-recon-settlement-summary b { font-size:11px; color:var(--text-muted); }
        .pos-recon-settlement-summary span { font-size:14px; font-weight:600; }
        .pos-recon-summary-financial div { background:var(--card-bg); }
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

        const profile_mode = cint(options.consolidate_pos_profiles)
            ? __("Eligible POS Profiles will be included in one Journal Entry; Commission and VAT debit lines remain split by POS Profile Cost Center.")
            : __("A separate Journal Entry will be created for each eligible POS Profile.");
        const bank_mode = cint(options.consolidate_bank_entries)
            ? __("Bank credits will be consolidated into two lines only: total Commission and total VAT.")
            : __("Bank Commission and Bank VAT credit lines will be separated by POS Profile.");
        const creation_mode = options.journal_entry_creation_mode || "Draft";

        frappe.prompt(
            [
                {
                    fieldname: "posting_date",
                    fieldtype: "Date",
                    label: __("Posting Date"),
                    default: frappe.datetime.get_today(),
                    reqd: 1,
                },
                {
                    fieldname: "posting_summary",
                    fieldtype: "HTML",
                    options: `<div class="pos-recon-accounting-preview">
                        <div><b>${__("Eligible Transactions")}</b>: ${cint(options.pending_count || 0)}</div>
                        <div><b>${__("POS Profiles")}</b>: ${cint(options.pos_profile_count || 0)}</div>
                        <div><b>${__("Commission")}</b>: ${pos_recon_money(options.commission)}</div>
                        <div><b>${__("VAT")}</b>: ${pos_recon_money(options.vat)}</div>
                        <div><b>${__("Total Bank Credit")}</b>: ${pos_recon_money(options.total)}</div>
                        <hr style="margin:10px 0;">
                        <div class="text-muted small">${profile_mode}<br>${bank_mode}<br>${__("Journal Entry mode")}: <b>${pos_recon_escape(creation_mode)}</b></div>
                    </div>`,
                },
            ],
            (values) => {
                frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.get_accounting_preview_for_run",
                    args: {
                        run_name: frm.doc.name,
                        posting_date: values.posting_date,
                    },
                    freeze: true,
                    freeze_message: __("Preparing accounting preview..."),
                }).then((preview_response) => {
                    const preview = preview_response.message || {};
                    const mode_text = preview.journal_entry_creation_mode === "Submit"
                        ? __("The generated Journal Entry/Entries will be submitted automatically.")
                        : __("The generated Journal Entry/Entries will be saved as Draft for Finance review.");
                    const message = __(
                        "Create {0} Journal Entry/Entries for {1} confirmed transactions using Posting Date {2}?<br><br>POS Profiles: {3}<br>Bank Commission: {4}<br>VAT: {5}<br>Total Bank Credit: {6}<br><br>{7}",
                        [
                            preview.journal_entry_count || 0,
                            preview.transaction_count || 0,
                            preview.posting_date || values.posting_date,
                            preview.pos_profile_count || 0,
                            pos_recon_money(preview.commission),
                            pos_recon_money(preview.vat),
                            pos_recon_money(preview.total),
                            mode_text,
                        ]
                    );
                    frappe.confirm(message, () => {
                        const auto_submit = preview.journal_entry_creation_mode === "Submit";
                        frappe.call({
                            method: "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.create_accounting_entries",
                            args: {
                                run_name: frm.doc.name,
                                posting_date: values.posting_date,
                            },
                            freeze: true,
                            freeze_message: auto_submit
                                ? __("Creating and submitting Journal Entries...")
                                : __("Creating Journal Entry drafts..."),
                        }).then((post_response) => {
                            const result = post_response.message || {};
                            const rows = (result.postings || []).map((row) => {
                                const state = cint(row.journal_entry_docstatus) === 1 ? __("Submitted") : __("Draft");
                                return `${pos_recon_escape(row.posting)} â†’ ${pos_recon_escape(row.journal_entry)} (${state})`;
                            }).join("<br>");
                            frappe.msgprint({
                                title: auto_submit ? __("POS Accounting Posted") : __("POS Accounting Drafts Created"),
                                indicator: auto_submit ? "green" : "blue",
                                message: __(
                                    "Processed {0} transactions in {1} Journal Entry/Entries.<br>Commission: {2}<br>VAT: {3}<br><br>{4}",
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
