frappe.ui.form.on("Bank Statement Reconciliation", {
    refresh(frm) {
        bsr_load(frm);
    },
    bank_account(frm) {
        bsr_load(frm);
    },
    tolerance(frm) {
        bsr_load(frm);
    },
});

function bsr_load(frm) {
    const filters = frm.__bsr_filters || {};
    const requestId = (frm.__bsr_request_id || 0) + 1;
    frm.__bsr_request_id = requestId;
    const field = frm.fields_dict.workspace_html;
    if (!field || !field.$wrapper) return;

    if (!frm.doc.bank_account) {
        field.$wrapper.html(
            bsr_styles() +
            `<div class="bsr-empty">${__("Select a Bank Account to load unreconciled Bank Statement and GL transactions.")}</div>`
        );
        return;
    }

    (frm.__bsr_sticky_observers || []).forEach(observer => observer.disconnect());
    frm.__bsr_sticky_observers = [];
    field.$wrapper.html(
        bsr_styles() +
        `<div class="bsr-loading">${__("Loading unreconciled transactions and matching by Reference #...")}</div>`
    );

    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.bank_statement_reconciliation.bank_statement_reconciliation.get_workspace",
        args: {
            bank_account: frm.doc.bank_account,
            tolerance: frm.doc.tolerance || 0.01,
            from_date: filters.from_date || "",
            to_date: filters.to_date || "",
            reference: filters.reference || "",
        },
    }).then((r) => {
        if (requestId !== frm.__bsr_request_id) return;
        frm.__bsr = r.message || {bank_rows: [], gl_rows: [], matches: [], counts: {}, summary: {}};
        bsr_render(frm);
    });
}

function bsr_render(frm) {
    (frm.__bsr_sticky_observers || []).forEach(observer => observer.disconnect());
    frm.__bsr_sticky_observers = [];
    const field = frm.fields_dict.workspace_html;
    if (!field || !field.$wrapper) return;
    const state = frm.__bsr || {bank_rows: [], gl_rows: [], matches: [], counts: {}};
    const canExclude = Boolean(state.can_exclude);

    const bankRows = state.bank_rows || [];
    const glRows = state.gl_rows || [];
    const matches = state.matches || [];

    const bankBody = bankRows.length
        ? bankRows.map((row) => `
            <tr data-bank-name="${bsr_escape(row.name)}">
                <td class="bsr-select-cell"><input type="checkbox" class="bsr-row-select" aria-label="${__("Select Bank row")}"></td>
                <td>${canExclude ? `<button class="btn btn-xs btn-default bsr-exclude-row" data-source-type="Bank Statement" data-record-name="${bsr_escape(row.name)}">${__("Exclude")}</button>` : "—"}</td>
                <td>${bsr_escape(row.date || "")}</td>
                <td><a href="${bsr_escape(bsr_transaction_href("Marina Bank Statement Transaction", row.name))}" target="_blank" rel="noopener noreferrer" class="bsr-open-doc">${bsr_escape(row.transaction_id || row.name)}</a></td>
                <td>${bsr_escape(row.reference_number || "—")}</td>
                <td class="bsr-description">${bsr_escape(row.description || "—")}</td>
                <td class="text-right">${bsr_money(row.amount)}</td>
                <td class="bsr-match-cell"><input type="text" inputmode="numeric" pattern="[1-9][0-9]{0,5}" maxlength="6" autocomplete="off" class="form-control input-xs bsr-match-input" placeholder="${__("Match #")}" aria-label="${__("Match #")}"></td>
            </tr>
        `).join("")
        : `<tr><td colspan="8" class="text-muted text-center">${__("No unreconciled Bank Statement rows.")}</td></tr>`;

    const glBody = glRows.length
        ? glRows.map((row) => `
            <tr data-gl-name="${bsr_escape(row.name)}">
                <td class="bsr-select-cell"><input type="checkbox" class="bsr-row-select" aria-label="${__("Select GL row")}"></td>
                <td>${canExclude ? `<button class="btn btn-xs btn-default bsr-exclude-row" data-source-type="GL Entry" data-record-name="${bsr_escape(row.name)}">${__("Exclude")}</button>` : "—"}</td>
                <td>${bsr_escape(row.date || "")}</td>
                <td><a href="${bsr_escape(bsr_transaction_href("GL Entry", row.name))}" target="_blank" rel="noopener noreferrer" class="bsr-open-doc">${bsr_escape(row.transaction_id || row.name)}</a></td>
                <td>${bsr_escape(row.reference_number || "—")}</td>
                <td class="bsr-description">${bsr_escape(row.description || "—")}</td>
                <td class="text-right">${bsr_money(row.amount)}</td>
                <td class="bsr-match-cell"><input type="text" inputmode="numeric" pattern="[1-9][0-9]{0,5}" maxlength="6" autocomplete="off" class="form-control input-xs bsr-match-input" placeholder="${__("Match #")}" aria-label="${__("Match #")}"></td>
            </tr>
        `).join("")
        : `<tr><td colspan="8" class="text-muted text-center">${__("No unreconciled GL Entries.")}</td></tr>`;

    const matchBody = matches.length
        ? matches.map((match, idx) => `
            <tr>
                <td>${idx + 1}</td>
                <td>${bsr_escape(match.match_type || "")}</td>
                <td>${bsr_escape(match.group_no || "—")}</td>
                <td>${bsr_escape(match.reference_number || "—")}</td>
                <td class="text-right">${bsr_money(match.bank_amount)}</td>
                <td class="text-right">${bsr_money(match.gl_amount)}</td>
                <td class="text-right">${bsr_money(match.difference)}</td>
                <td>${(match.bank_rows || []).length}</td>
                <td>${(match.gl_rows || []).length}</td>
                <td><span class="indicator-pill green">${__("Ready to Save")}</span></td>
            </tr>
        `).join("")
        : `<tr><td colspan="10" class="text-muted text-center">${__("No matches prepared yet.")}</td></tr>`;

    field.$wrapper.html(`
        ${bsr_styles()}
        <div class="bsr-toolbar">
            <div>
                <div class="bsr-title">${__("Bank Statement Reconciliation")}</div>
                <div class="text-muted small">${__("Reference # is matched first by grouped totals, regardless of date. Enter the same Match # against one or more Bank and GL rows to match them manually.")}</div>
            </div>
            <div class="bsr-actions">
                <button class="btn btn-xs btn-default bsr-refresh">${__("Refresh")}</button>
                <button class="btn btn-xs btn-default bsr-view-excluded">${__("View Excluded Transactions")}</button>
                <button class="btn btn-xs btn-default bsr-apply-manual">${__("Apply Manual Matches")}</button>
                <button class="btn btn-xs btn-primary bsr-save" ${matches.length ? "" : "disabled"}>${__("Save Reconciliation")}</button>
            </div>
        </div>

        ${bsr_filter_html(frm.__bsr_filters || {})}
        ${bsr_summary_html(state.summary || {})}

        <div class="bsr-counts">
            <span class="indicator-pill orange">${bankRows.length} ${__("Bank Rows to Link")}</span>
            <span class="indicator-pill orange">${glRows.length} ${__("GL Rows to Link")}</span>
            <span class="indicator-pill blue">${matches.length} ${__("Prepared Matches")}</span>
        </div>

        <div class="bsr-selection-summary">${__("Selected Difference")}: <strong class="bsr-selection-difference">${bsr_money(0)}</strong></div>
        <div class="bsr-grid">
            <div class="bsr-panel">
                <div class="bsr-panel-title">${__("Unreconciled Bank Statement")}</div>
                <button type="button" class="btn btn-xs btn-default bsr-columns-button" data-side="bank">${__("Columns")}</button>
                <div class="bsr-selected-card" data-selected-side="bank">${__("Selected Bank Amount")}: <strong class="bsr-selected-total">0.00</strong> <span class="bsr-selected-count">(0)</span></div>
                <div class="bsr-table-wrap">
                    <table class="table table-bordered table-hover bsr-table bsr-config-table" data-side="bank">
                        <thead><tr>
                            <th>${__("Select")}</th>
                            <th>${__("Actions")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Transaction ID")}</th>
                            <th>${__("Reference #")}</th>
                            <th>${__("Description")}</th>
                            <th class="text-right">${__("Amount")}</th>
                            <th>${__("Match #")}</th>
                        </tr>
                        ${bsr_column_filter_header("bank")}
                        </thead>
                        <tbody>${bankBody}</tbody>
                    </table>
                </div>
            </div>

            <div class="bsr-panel">
                <div class="bsr-panel-title">${__("Unreconciled GL Entries")}</div>
                <button type="button" class="btn btn-xs btn-default bsr-columns-button" data-side="gl">${__("Columns")}</button>
                <div class="bsr-selected-card" data-selected-side="gl">${__("Selected GL Amount")}: <strong class="bsr-selected-total">0.00</strong> <span class="bsr-selected-count">(0)</span></div>
                <div class="bsr-table-wrap">
                    <table class="table table-bordered table-hover bsr-table bsr-config-table" data-side="gl">
                        <thead><tr>
                            <th>${__("Select")}</th>
                            <th>${__("Actions")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Transaction ID")}</th>
                            <th>${__("Reference #")}</th>
                            <th>${__("Description")}</th>
                            <th class="text-right">${__("Amount")}</th>
                            <th>${__("Match #")}</th>
                        </tr>
                        ${bsr_column_filter_header("gl")}
                        </thead>
                        <tbody>${glBody}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="bsr-panel bsr-results">
            <div class="bsr-panel-title">${__("Reconciliation Results")}</div>
            <div class="bsr-table-wrap">
                <table class="table table-bordered table-hover bsr-table">
                    <thead><tr>
                        <th>#</th>
                        <th>${__("Match Type")}</th>
                        <th>${__("Match #")}</th>
                        <th>${__("Reference #")}</th>
                        <th class="text-right">${__("Bank Amount")}</th>
                        <th class="text-right">${__("GL Amount")}</th>
                        <th class="text-right">${__("Difference")}</th>
                        <th>${__("Bank Lines")}</th>
                        <th>${__("GL Lines")}</th>
                        <th>${__("Status")}</th>
                    </tr></thead>
                    <tbody>${matchBody}</tbody>
                </table>
            </div>
        </div>
    `);

    bsr_bind(frm);
    bsr_setup_columns(frm);
    bsr_bind_table_search(frm);
    bsr_bind_selection(frm);
    bsr_setup_sticky_headers(frm);
}

// Independent, display-only column filtering for Bank and GL tables.
function bsr_column_filter_header(side) {
    return '<tr class="bsr-column-filter-row">' + BSR_COLUMN_NAMES.map((name, i) => {
        if (i < 2) return '<td></td>'; // Select and Actions are not searchable.
        return '<td><input type="text" class="form-control input-xs bsr-column-search" ' +
            'data-side="' + side + '" data-column="' + i + '" ' +
            'autocomplete="off" placeholder="' + bsr_escape(__("Search")) + '" ' +
            'aria-label="' + bsr_escape(__("Filter") + " " + __(name)) + '"></td>';
    }).join("") + '</tr>';
}

function bsr_apply_table_search(frm, side) {
    const $table = frm.fields_dict.workspace_html.$wrapper
        .find('.bsr-config-table[data-side="' + side + '"]');
    const filters = (frm.__bsr_table_search || {})[side] || {};
    $table.find("tbody tr[data-bank-name], tbody tr[data-gl-name]").each(function () {
        const $row = $(this);
        const visible = Object.entries(filters).every(([column, needle]) => {
            const $cell = $row.children().eq(Number(column));
            const value = Number(column) === 7
                ? String($cell.find(".bsr-match-input").val() || "")
                : $cell.text();
            return value.toLocaleLowerCase().includes(needle.toLocaleLowerCase());
        });
        $row.toggle(visible);
    });
}

function bsr_bind_table_search(frm) {
    const $wrapper = frm.fields_dict.workspace_html.$wrapper;
    frm.__bsr_table_search = frm.__bsr_table_search || {bank: {}, gl: {}};
    $wrapper.find(".bsr-column-search").each(function () {
        const $input = $(this), side = $input.attr("data-side");
        const column = $input.attr("data-column");
        $input.val((frm.__bsr_table_search[side] || {})[column] || "");
    }).on("input", function () {
        const $input = $(this), side = $input.attr("data-side"), column = $input.attr("data-column");
        const value = String($input.val() || "").trim();
        const filters = frm.__bsr_table_search[side] || {};
        if (value) filters[column] = value;
        else delete filters[column];
        frm.__bsr_table_search[side] = filters;
        bsr_apply_table_search(frm, side);
    });
    $wrapper.find(".bsr-match-input").on("input", function () {
        // Typing/paste only; strip non-digits and enforce the existing six-digit limit.
        const input = this;
        const raw = String(input.value || "");
        const clean = raw.replace(/\\D/g, "").slice(0, 6);
        if (clean !== raw) input.value = clean;
        const side = $(this).closest(".bsr-config-table").attr("data-side");
        if ((frm.__bsr_table_search[side] || {})["7"]) bsr_apply_table_search(frm, side);
    });
    for (const side of ["bank", "gl"]) bsr_apply_table_search(frm, side);
}

function bsr_bind(frm) {
    const $w = frm.fields_dict.workspace_html.$wrapper;

    $w.find(".bsr-refresh").on("click", () => bsr_reload_confirm(frm, () => bsr_load(frm)));
    $w.find(".bsr-apply-filters").on("click", () => {
        const fromDate = String($w.find(".bsr-from-date").val() || "");
        const toDate = String($w.find(".bsr-to-date").val() || "");
        if (fromDate && toDate && fromDate > toDate) {
            frappe.msgprint(__("From Date must be on or before To Date."));
            return;
        }
        const next = {
            from_date: fromDate,
            to_date: toDate,
            reference: String($w.find(".bsr-reference").val() || "").trim(),
        };
        bsr_reload_confirm(frm, () => { frm.__bsr_filters = next; bsr_load(frm); });
    });
    $w.find(".bsr-clear-filters").on("click", () => {
        bsr_reload_confirm(frm, () => { frm.__bsr_filters = {}; bsr_load(frm); });
    });
    $w.find(".bsr-view-excluded").on("click", () => {
        frappe.set_route("List", "Bank Reconciliation Exclusion", {
            bank_account: frm.doc.bank_account,
            status: "Excluded",
        });
    });
    $w.find(".bsr-exclude-row").on("click", function () {
        bsr_exclude_row(frm, $(this).attr("data-source-type"), $(this).attr("data-record-name"));
    });

    $w.find(".bsr-apply-manual").on("click", () => bsr_apply_manual(frm));
    $w.find(".bsr-save").on("click", () => bsr_save(frm));
}


function bsr_exclude_row(frm, sourceType, recordName) {
    if (!frm.doc.bank_account || !recordName) return;
    const options = "POS / Sales Transaction\nDuplicate Transaction\nHistorical Transaction\nOut of Reconciliation Scope\nOther";
    frappe.prompt(
        [
            {
                fieldname: "reason", fieldtype: "Select", options: options,
                label: __("Exclusion Reason"), reqd: 1
            },
            {
                fieldname: "comments", fieldtype: "Small Text",
                label: __("Comments")
            }
        ],
        (values) => {
            bsr_reload_confirm(frm, () => {
                frappe.call({
                    method: "marina_custom_apps.pos_reconciliation.doctype.bank_statement_reconciliation.bank_statement_reconciliation.exclude_transaction",
                    args: {
                        bank_account: frm.doc.bank_account,
                        source_type: sourceType,
                        record_name: recordName,
                        reason: values.reason,
                        comments: values.comments || "",
                    },
                    freeze: true,
                }).then(() => {
                    frappe.show_alert({message: __("Transaction excluded. Restore it through Excluded Transactions."), indicator: "green"}, 5);
                    bsr_load(frm);
                });
            });
        },
        __("Exclude {0}: {1}", [sourceType, recordName]),
        __("Exclude")
    );
}


function bsr_collect_match_inputs(frm) {
    const $w = frm.fields_dict.workspace_html.$wrapper;
    const state = frm.__bsr || {};
    const bankRows = (state.bank_rows || []).map((row) => ({ ...row }));
    const glRows = (state.gl_rows || []).map((row) => ({ ...row }));
    const bankLookup = Object.fromEntries(bankRows.map((row) => [row.name, row]));
    const glLookup = Object.fromEntries(glRows.map((row) => [row.name, row]));
    $w.find("tr[data-bank-name]").each(function () {
        const row = bankLookup[$(this).attr("data-bank-name")];
        if (row) row.group_no = String($(this).find(".bsr-match-input").val() || "").trim();
    });
    $w.find("tr[data-gl-name]").each(function () {
        const row = glLookup[$(this).attr("data-gl-name")];
        if (row) row.group_no = String($(this).find(".bsr-match-input").val() || "").trim();
    });
    return { bankRows, glRows };
}

// No accounting writes: this prepares groups for server-side validation on Save.
function bsr_build_manual_matches(bankRows, glRows, tolerance) {
    const groups = new Map();
    const errors = [];
    const pattern = /^[1-9][0-9]{0,5}$/;
    const add = (row, side) => {
        const id = String(row.group_no || "").trim();
        if (!id) return;
        if (!pattern.test(id)) {
            errors.push(__("Invalid Match # on {0} row {1}: {2}. Enter a positive whole number (1–999999).", [
                side, row.row_no, id,
            ]));
            return;
        }
        if (!groups.has(id)) groups.set(id, { bank_rows: [], gl_rows: [] });
        groups.get(id)[side === "Bank" ? "bank_rows" : "gl_rows"].push(row);
    };
    bankRows.forEach((row) => add(row, "Bank"));
    glRows.forEach((row) => add(row, "GL"));

    const matches = [];
    const limit = Math.abs(Number(tolerance || 0.01));
    for (const [group, rows] of groups) {
        if (!rows.bank_rows.length || !rows.gl_rows.length) {
            errors.push(__("Match # {0} must contain at least one Bank and one GL row.", [group]));
            continue;
        }
        const bank = bsr_round(rows.bank_rows.reduce((total, row) => total + Number(row.amount || 0), 0));
        const gl = bsr_round(rows.gl_rows.reduce((total, row) => total + Number(row.amount || 0), 0));
        const difference = bsr_round(bank - gl);
        if (Math.abs(difference) > limit + 0.000001) {
            errors.push(__("Match # {0}: Bank {1}, GL {2}, difference {3} exceeds tolerance.", [
                group, bsr_money(bank), bsr_money(gl), bsr_money(difference),
            ]));
            continue;
        }
        matches.push({
            match_type: "Manual Group", group_no: group,
            reference_number: rows.bank_rows.map((r) => r.reference_number).find(Boolean)
                || rows.gl_rows.map((r) => r.reference_number).find(Boolean) || "",
            bank_amount: bank, gl_amount: gl, difference,
            bank_rows: rows.bank_rows, gl_rows: rows.gl_rows,
        });
    }
    matches.sort((a, b) => Number(a.group_no) - Number(b.group_no));
    return { matches, errors };
}

function bsr_apply_manual(frm) {
    const { bankRows, glRows } = bsr_collect_match_inputs(frm);
    const result = bsr_build_manual_matches(bankRows, glRows, frm.doc.tolerance || 0.01);
    if (result.errors.length) {
        frappe.msgprint({
            title: __("Manual Match Groups Not Valid"),
            indicator: "orange",
            message: result.errors.map((message) => bsr_escape(message)).join("<br>"),
        });
        return;
    }
    if (!result.matches.length) {
        frappe.msgprint(__("Enter the same Match # on Bank and GL rows to prepare manual reconciliation."));
        return;
    }
    const state = frm.__bsr || {};
    const bankIds = new Set(result.matches.flatMap((m) => m.bank_rows.map((row) => row.name)));
    const glIds = new Set(result.matches.flatMap((m) => m.gl_rows.map((row) => row.name)));
    state.matches = (state.matches || []).concat(result.matches);
    state.bank_rows = bankRows.filter((row) => !bankIds.has(row.name));
    state.gl_rows = glRows.filter((row) => !glIds.has(row.name));
    state.bank_rows.forEach((row, idx) => { row.row_no = idx + 1; });
    state.gl_rows.forEach((row, idx) => { row.row_no = idx + 1; });
    bsr_render(frm);
}

function bsr_save(frm) {
    const $w = frm.fields_dict.workspace_html.$wrapper;
    const unapplied = $w.find(".bsr-match-input").toArray().some(
        (input) => String($(input).val() || "").trim()
    );
    if (unapplied) {
        frappe.msgprint(__("Some rows still have unapplied Match # values. Apply Manual Matches before saving reconciliation."));
        return;
    }
    const state = frm.__bsr || {};
    const matches = state.matches || [];
    if (!matches.length) {
        frappe.msgprint(__("There are no prepared matches to save."));
        return;
    }

    const payload = matches.map((match) => ({
        match_type: match.match_type,
        reference_number: match.reference_number || "",
        bank_names: (match.bank_rows || []).map((row) => row.name),
        gl_names: (match.gl_rows || []).map((row) => row.name),
    }));

    frappe.confirm(
        __("Save {0} reconciliation match(es)? Matching Bank Statement rows will be marked Reconciled.", [matches.length]),
        () => {
            frappe.call({
                method: "marina_custom_apps.pos_reconciliation.doctype.bank_statement_reconciliation.bank_statement_reconciliation.save_matches",
                args: {
                    bank_account: frm.doc.bank_account,
                    matches: payload,
                    tolerance: frm.doc.tolerance || 0.01,
                },
                freeze: true,
                freeze_message: __("Saving bank reconciliation..."),
            }).then((r) => {
                const result = r.message || {};
                frappe.show_alert({
                    message: __("{0} match(es) saved; {1} Bank rows reconciled.", [
                        cint(result.match_count || 0),
                        cint(result.bank_rows_reconciled || 0),
                    ]),
                    indicator: "green",
                }, 6);
                bsr_load(frm);
            });
        }
    );
}


function bsr_filter_html(filters) {
    return `
        <div class="bsr-panel bsr-filter-panel">
            <div class="bsr-panel-title">${__("Reconciliation Filters")}</div>
            <div class="bsr-filter-grid">
                <label>${__("From Date")}
                    <input type="date" class="form-control input-sm bsr-from-date" value="${bsr_escape(filters.from_date || "")}">
                </label>
                <label>${__("To Date")}
                    <input type="date" class="form-control input-sm bsr-to-date" value="${bsr_escape(filters.to_date || "")}">
                </label>
                <label>${__("Search")}
                    <input type="text" class="form-control input-sm bsr-reference" placeholder="${__("Amount, Reference #, Description")}" value="${bsr_escape(filters.reference || "")}">
                </label>
                <div class="bsr-filter-buttons">
                    <button class="btn btn-sm btn-primary bsr-apply-filters">${__("Apply Filters")}</button>
                    <button class="btn btn-sm btn-default bsr-clear-filters">${__("Clear")}</button>
                </div>
            </div>
        </div>
    `;
}

function bsr_summary_html(summary) {
    const rows = [
        [
            ["Reconciled Bank Transactions", summary.reconciled_bank_transactions, false],
            ["Reconciled GL Transactions", summary.reconciled_gl_transactions, false],
            ["Reconciled Bank Amt", summary.reconciled_bank_amount, true],
            ["Reconciled GL Amt", summary.reconciled_gl_amount, true],
        ],
        [
            ["Unreconciled Bank Transactions", summary.unreconciled_bank_transactions, false],
            ["Unreconciled GL Transactions", summary.unreconciled_gl_transactions, false],
            ["Unreconciled Bank Amt", summary.unreconciled_bank_amount, true],
            ["Unreconciled GL Amt", summary.unreconciled_gl_amount, true],
        ],
    ];
    return `
        <div class="bsr-summary">
            ${rows.map((items) => `
                <div class="bsr-summary-row">
                    ${items.map(([label, value, currency]) => `
                        <div class="bsr-summary-card">
                            <div class="bsr-summary-label">${__(label)}</div>
                            <div class="bsr-summary-value">${currency ? bsr_money(value) : cint(value || 0)}</div>
                        </div>
                    `).join("")}
                </div>
            `).join("")}
        </div>
        <div class="text-muted small bsr-filter-note">
            ${__("Amounts are signed net bank movements. Prepared matches remain unreconciled until saved. Only complete reference groups within the selected filters are prepared automatically.")}
        </div>
    `;
}

function bsr_reload_confirm(frm, action) {
    const state = frm.__bsr || {};
    const hasManual = (state.matches || []).some((match) =>
        ["Manual TR", "Manual Group"].includes(match.match_type)
    );
    const $w = frm.fields_dict.workspace_html.$wrapper;
    const hasTypedLinks = $w.find(".bsr-match-input").toArray().some((el) => String($(el).val() || "").trim());
    if (hasManual || hasTypedLinks) {
        frappe.confirm(
            __("Refreshing or changing filters will discard unsaved manual Match # groups. Continue?"),
            action
        );
    } else {
        action();
    }
}

function bsr_round(value) {
    return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
}

function bsr_money(value) {
    const number = Number(value || 0);
    return format_currency(number, frappe.defaults.get_default("currency") || "SAR");
}

function bsr_transaction_href(doctype, name) {
    // Real, browser-navigable links preserve the reconciliation working tab.
    // Explicit route slugs avoid dependence on the Frappe client router's state.
    const routes = {
        "GL Entry": "gl-entry",
        "Marina Bank Statement Transaction": "marina-bank-statement-transaction",
    };
    const route = routes[doctype];
    if (!route || !name) return "#";
    return "/app/" + route + "/" + encodeURIComponent(String(name));
}

function bsr_escape(value) {
    return frappe.utils.escape_html(String(value === null || value === undefined ? "" : value));
}

function bsr_styles() {
    return `<style>
        .bsr-loading,.bsr-empty{padding:24px;text-align:center;color:var(--text-muted);border:1px dashed var(--border-color);border-radius:var(--border-radius-md);}
        .bsr-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;}
        .bsr-title{font-size:15px;font-weight:700;}
        .bsr-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;}
        .bsr-counts{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 12px;}
        .bsr-filter-panel{margin-bottom:12px;}
        .bsr-filter-grid{display:grid;grid-template-columns:1fr 1fr 1.5fr auto;gap:10px;align-items:end;}
        .bsr-filter-grid label{display:block;margin:0;font-size:12px;font-weight:600;}
        .bsr-filter-grid input{margin-top:4px;}
        .bsr-filter-buttons{display:flex;gap:6px;align-items:center;min-height:30px;}
        .bsr-summary{display:flex;flex-direction:column;gap:8px;margin-bottom:4px;}
        .bsr-summary-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;}
        .bsr-summary-card{background:var(--control-bg);border:1px solid var(--border-color);border-radius:var(--border-radius-md);padding:10px;min-width:0;}
        .bsr-summary-label{font-size:11px;color:var(--text-muted);font-weight:600;min-height:30px;}
        .bsr-summary-value{font-size:18px;font-weight:700;overflow-wrap:anywhere;font-variant-numeric:tabular-nums;}
        .bsr-filter-note{margin:6px 0 10px;}
        .bsr-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start;}
        .bsr-panel{border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg);padding:10px;min-width:0;}
        .bsr-panel-title{font-weight:600;margin-bottom:8px;}
        .bsr-results{margin-top:12px;}
        .bsr-table-wrap{overflow:auto;max-height:520px;position:relative;}
        /* Both rows stay fixed inside each table's own vertical scroll area. */
        .bsr-config-table thead tr:first-child > th{position:sticky !important;top:0;z-index:5;background:var(--card-bg);background-clip:padding-box;}
        .bsr-config-table thead tr.bsr-column-filter-row > td{position:sticky;top:var(--bsr-header-height, 33px);z-index:4;background:var(--control-bg);background-clip:padding-box;}
        .bsr-config-table thead tr:first-child > th .bsr-col-resize{z-index:6;}
        .bsr-table{margin:0;min-width:760px;}
        .bsr-table th,.bsr-table td{font-size:11px;vertical-align:middle !important;white-space:nowrap;}
        .bsr-config-table{table-layout:fixed;min-width:0;width:max-content;}
        .bsr-config-table th,.bsr-config-table td{box-sizing:border-box;white-space:normal !important;overflow-wrap:anywhere;word-break:break-word;overflow:hidden;line-height:1.45;}
        .bsr-config-table td a{white-space:normal !important;overflow-wrap:anywhere;word-break:break-word;}
        .bsr-config-table td.text-right{overflow-wrap:anywhere;}
        .bsr-config-table .bsr-select-cell{text-align:center;vertical-align:middle !important;}
        .bsr-selected-card{background:var(--control-bg);border:1px solid var(--border-color);padding:8px 10px;border-radius:6px;margin:7px 0;font-size:12px;}
        .bsr-selected-total{font-variant-numeric:tabular-nums;font-size:15px;}
        .bsr-selected-count{color:var(--text-muted);}
        .bsr-column-filter-row td{padding:3px !important;background:var(--control-bg);vertical-align:middle !important;}
        .bsr-column-search{width:100%;min-width:0;font-size:11px !important;padding:2px 4px !important;}
        .bsr-config-table td.bsr-description{white-space:normal !important;overflow-wrap:anywhere;word-break:normal;line-height:1.4;}
        .bsr-col-resize{position:absolute;right:0;top:0;bottom:0;width:8px;cursor:col-resize;z-index:2;}
        .bsr-config-table th{position:relative;}
        .bsr-columns-button{margin-bottom:6px;}
        .bsr-columns-menu{display:flex;flex-wrap:wrap;gap:8px;padding:8px;margin-bottom:8px;border:1px solid var(--border-color);border-radius:5px;}
        .bsr-match-cell{min-width:95px;}
        .bsr-match-input{width:100%;min-width:75px;text-align:center;}
        @media(max-width:1200px){.bsr-grid{grid-template-columns:1fr;}.bsr-filter-grid{grid-template-columns:1fr 1fr;}}
        @media(max-width:700px){.bsr-summary-row{grid-template-columns:1fr 1fr;}.bsr-filter-grid{grid-template-columns:1fr;}}
    </style>`;
}


const BSR_COLUMN_NAMES = ["Select", "Actions", "Date", "Transaction ID", "Reference #", "Description", "Amount", "Match #"];
const BSR_COLUMN_DEFAULTS = [65, 74, 100, 165, 145, 270, 140, 105];

function bsr_column_key(side) {
    const user = (frappe.session && frappe.session.user) || "unknown";
    return "marina_bsr_columns_v1:" + user + ":" + side;
}

function bsr_column_preferences(side) {
    const fallback = {visible: Array(8).fill(true), widths: BSR_COLUMN_DEFAULTS.slice()};
    try {
        const saved = JSON.parse(localStorage.getItem(bsr_column_key(side)) || "null");
        if (!saved || !Array.isArray(saved.visible) || !Array.isArray(saved.widths)) return fallback;
        // Preserve users\' existing seven-column preferences when adding Select.
        if (saved.visible.length === 7 && saved.widths.length === 7) {
            saved.visible.unshift(true);
            saved.widths.unshift(BSR_COLUMN_DEFAULTS[0]);
        }
        if (saved.visible.length !== 8 || saved.widths.length !== 8) return fallback;
        return {
            visible: saved.visible.map((v, i) => i === 0 || i === 6 || i === 7 ? true : Boolean(v)),
            widths: saved.widths.map((w, i) => Math.max(64, Math.min(800, Number(w) || BSR_COLUMN_DEFAULTS[i]))),
        };
    } catch (e) { return fallback; }
}

function bsr_save_column_preferences(side, prefs) {
    try { localStorage.setItem(bsr_column_key(side), JSON.stringify(prefs)); }
    catch (e) { frappe.show_alert({message: __("Could not save column settings in this browser."), indicator: "orange"}); }
}

function bsr_apply_columns($table, side, prefs) {
    $table.find("colgroup").remove();
    const $group = $('<colgroup></colgroup>');
    prefs.widths.forEach((width, i) => {
        const $col = $("<col>");
        $col.css("width", width + "px");
        if (!prefs.visible[i]) $col.css("visibility", "collapse");
        $group.append($col);
    });
    $table.prepend($group);
    let total = 0;
    for (let i = 0; i < 8; i++) {
        const show = prefs.visible[i], width = prefs.widths[i];
        $table.find("tr").each(function () {
            const $cells = $(this).children();
            if ($cells.length !== 8) return; // Keep full-width empty-state messages.
            $cells.eq(i).toggle(show).css("width", show ? width + "px" : "");
        });
        if (show) total += width;
    }
    $table.css("width", total + "px");
    $table.find("thead th").each(function (index) {
        const $th = $(this);
        $th.find(".bsr-col-resize").remove();
        if (!prefs.visible[index]) return;
        $("<span class='bsr-col-resize' aria-label='Resize column'></span>")
            .appendTo($th)
            .on("pointerdown", function (event) {
                if (event.button !== 0) return;
                event.preventDefault();
                const startX = event.clientX, initial = prefs.widths[index];
                const ns = ".bsrresize" + side;
                $(document).on("pointermove" + ns, function (moveEvent) {
                    prefs.widths[index] = Math.max(64, Math.min(800, initial + moveEvent.clientX - startX));
                    // Resize only table columns, not every transaction row, on pointer movement.
                    $table.children("colgroup").children("col").eq(index)
                        .css("width", prefs.widths[index] + "px");
                    const visibleWidth = prefs.widths.reduce(
                        (sum, width, i) => sum + (prefs.visible[i] ? width : 0), 0
                    );
                    $table.css("width", visibleWidth + "px");
                }).one("pointerup" + ns + " pointercancel" + ns, function () {
                    $(document).off(ns);
                    bsr_apply_columns($table, side, prefs);
                    bsr_save_column_preferences(side, prefs);
                });
            });
    });
}

function bsr_setup_sticky_headers(frm) {
    const $wrapper = frm.fields_dict.workspace_html.$wrapper;
    $wrapper.find(".bsr-config-table").each(function () {
        const table = this;
        const header = table.querySelector("thead tr:first-child");
        if (!header) return;
        const update = () => {
            const height = header.getBoundingClientRect().height;
            if (height > 0) table.style.setProperty("--bsr-header-height", height + "px");
        };
        update();
        // Column resizing and viewport changes can wrap header labels differently.
        if (typeof ResizeObserver !== "undefined") {
            const observer = new ResizeObserver(update);
            observer.observe(header);
            // Avoid leaking observers when the workspace is re-rendered.
            const previous = frm.__bsr_sticky_observers || [];
            previous.push(observer);
            frm.__bsr_sticky_observers = previous;
        }
    });
}

function bsr_setup_columns(frm) {
    const $wrapper = frm.fields_dict.workspace_html.$wrapper;
    $wrapper.find(".bsr-config-table").each(function () {
        const $table = $(this), side = $table.attr("data-side");
        bsr_apply_columns($table, side, bsr_column_preferences(side));
    });
    $wrapper.find(".bsr-columns-button").on("click", function () {
        const side = $(this).attr("data-side");
        const $table = $wrapper.find(".bsr-config-table[data-side='" + side + "']");
        const $panel = $(this).closest(".bsr-panel");
        $panel.find(".bsr-columns-menu").remove();
        const prefs = bsr_column_preferences(side);
        const $menu = $('<div class="bsr-columns-menu"></div>');
        BSR_COLUMN_NAMES.forEach((name, index) => {
            const $label = $('<label style="margin:0;font-weight:normal;"></label>');
            const $check = $('<input type="checkbox" style="margin-right:4px;">')
                .prop("checked", prefs.visible[index])
                .prop("disabled", index === 0 || index === 6 || index === 7);
            $check.on("change", function () {
                prefs.visible[index] = $(this).prop("checked");
                bsr_save_column_preferences(side, prefs);
                bsr_apply_columns($table, side, prefs);
            });
            $label.append($check).append(document.createTextNode(__(name)));
            $menu.append($label);
        });
        const $reset = $('<button type="button" class="btn btn-xs btn-default"></button>').text(__("Reset"));
        $reset.on("click", function () {
            const reset = {visible: Array(8).fill(true), widths: BSR_COLUMN_DEFAULTS.slice()};
            bsr_save_column_preferences(side, reset);
            bsr_apply_columns($table, side, reset);
            $menu.remove();
        });
        $menu.append($reset);
        $(this).after($menu);
    });
}


function bsr_bind_selection(frm) {
    const $wrapper = frm.fields_dict.workspace_html.$wrapper;
    const update = () => {
        const totals = {};
        for (const side of ["bank", "gl"]) {
            const $table = $wrapper.find('.bsr-config-table[data-side="' + side + '"]');
            const rows = (frm.__bsr || {})[side === "bank" ? "bank_rows" : "gl_rows"] || [];
            const lookup = new Map(rows.map(row => [String(row.name), Number(row.amount || 0)]));
            let amount = 0, count = 0;
            $table.find("tbody tr").each(function () {
                const $tr = $(this);
                if (!$tr.find(".bsr-row-select").prop("checked")) return;
                const key = $tr.attr(side === "bank" ? "data-bank-name" : "data-gl-name");
                if (!lookup.has(key)) return;
                amount += lookup.get(key);
                count++;
            });
            totals[side] = amount;
            const $card = $wrapper.find('.bsr-selected-card[data-selected-side="' + side + '"]');
            $card.find(".bsr-selected-total").text(bsr_money(Math.round(amount * 100) / 100));
            $card.find(".bsr-selected-count").text("(" + count + " " + __("selected") + ")");
        }
        const difference = Math.round((totals.bank - totals.gl) * 100) / 100;
        $wrapper.find(".bsr-selection-difference").text(bsr_money(difference));
    };
    $wrapper.find(".bsr-row-select").on("change", update);
    update();
}
