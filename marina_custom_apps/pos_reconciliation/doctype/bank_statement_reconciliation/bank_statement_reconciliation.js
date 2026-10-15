frappe.ui.form.on("Bank Statement Reconciliation", {
    refresh(frm) {
        frm.disable_save();
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
    const field = frm.fields_dict.workspace_html;
    if (!field || !field.$wrapper) return;

    if (!frm.doc.bank_account) {
        field.$wrapper.html(
            bsr_styles() +
            `<div class="bsr-empty">${__("Select a Bank Account to load unreconciled Bank Statement and GL transactions.")}</div>`
        );
        return;
    }

    field.$wrapper.html(
        bsr_styles() +
        `<div class="bsr-loading">${__("Loading unreconciled transactions and matching by Reference #...")}</div>`
    );

    frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.bank_statement_reconciliation.bank_statement_reconciliation.get_workspace",
        args: {
            bank_account: frm.doc.bank_account,
            tolerance: frm.doc.tolerance || 0.01,
        },
    }).then((r) => {
        frm.__bsr = r.message || {bank_rows: [], gl_rows: [], matches: [], counts: {}};
        bsr_render(frm);
    });
}

function bsr_render(frm) {
    const field = frm.fields_dict.workspace_html;
    if (!field || !field.$wrapper) return;
    const state = frm.__bsr || {bank_rows: [], gl_rows: [], matches: [], counts: {}};

    const bankRows = state.bank_rows || [];
    const glRows = state.gl_rows || [];
    const matches = state.matches || [];

    const bankBody = bankRows.length
        ? bankRows.map((row) => `
            <tr data-bank-name="${bsr_escape(row.name)}">
                <td>${bsr_escape(row.date || "")}</td>
                <td><a href="#" class="bsr-open-doc" data-doctype="Marina Bank Statement Transaction" data-name="${bsr_escape(row.name)}">${bsr_escape(row.transaction_id || row.name)}</a></td>
                <td>${bsr_escape(row.reference_number || "—")}</td>
                <td class="bsr-description">${bsr_escape(row.description || "—")}</td>
                <td class="text-right">${bsr_money(row.amount)}</td>
                <td style="width:80px"><input type="number" min="1" step="1" class="form-control input-xs bsr-tr-input" placeholder="TR#"></td>
            </tr>
        `).join("")
        : `<tr><td colspan="6" class="text-muted text-center">${__("No unreconciled Bank Statement rows.")}</td></tr>`;

    const glBody = glRows.length
        ? glRows.map((row) => `
            <tr data-gl-name="${bsr_escape(row.name)}" data-tr-no="${cint(row.tr_no)}">
                <td><b>${cint(row.tr_no)}</b></td>
                <td>${bsr_escape(row.date || "")}</td>
                <td><a href="#" class="bsr-open-doc" data-doctype="GL Entry" data-name="${bsr_escape(row.name)}">${bsr_escape(row.transaction_id || row.name)}</a></td>
                <td>${bsr_escape(row.reference_number || "—")}</td>
                <td class="bsr-description">${bsr_escape(row.description || "—")}</td>
                <td class="text-right">${bsr_money(row.amount)}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="6" class="text-muted text-center">${__("No unreconciled GL Entries.")}</td></tr>`;

    const matchBody = matches.length
        ? matches.map((match, idx) => `
            <tr>
                <td>${idx + 1}</td>
                <td>${bsr_escape(match.match_type || "")}</td>
                <td>${bsr_escape(match.reference_number || "—")}</td>
                <td class="text-right">${bsr_money(match.bank_amount)}</td>
                <td class="text-right">${bsr_money(match.gl_amount)}</td>
                <td class="text-right">${bsr_money(match.difference)}</td>
                <td>${(match.bank_rows || []).length}</td>
                <td>${(match.gl_rows || []).length}</td>
                <td><span class="indicator-pill green">${__("Ready to Save")}</span></td>
            </tr>
        `).join("")
        : `<tr><td colspan="9" class="text-muted text-center">${__("No matches prepared yet.")}</td></tr>`;

    field.$wrapper.html(`
        ${bsr_styles()}
        <div class="bsr-toolbar">
            <div>
                <div class="bsr-title">${__("Bank Statement Reconciliation")}</div>
                <div class="text-muted small">${__("Reference # is matched first by grouped totals, regardless of date. Use GL TR# for manual matching.")}</div>
            </div>
            <div class="bsr-actions">
                <button class="btn btn-xs btn-default bsr-refresh">${__("Refresh")}</button>
                <button class="btn btn-xs btn-default bsr-apply-manual">${__("Apply Manual TR Links")}</button>
                <button class="btn btn-xs btn-primary bsr-save" ${matches.length ? "" : "disabled"}>${__("Save Reconciliation")}</button>
            </div>
        </div>

        <div class="bsr-counts">
            <span class="indicator-pill orange">${bankRows.length} ${__("Bank Unreconciled")}</span>
            <span class="indicator-pill orange">${glRows.length} ${__("GL Unreconciled")}</span>
            <span class="indicator-pill blue">${matches.length} ${__("Prepared Matches")}</span>
        </div>

        <div class="bsr-grid">
            <div class="bsr-panel">
                <div class="bsr-panel-title">${__("Unreconciled Bank Statement")}</div>
                <div class="bsr-table-wrap">
                    <table class="table table-bordered table-hover bsr-table">
                        <thead><tr>
                            <th>${__("Date")}</th>
                            <th>${__("Transaction ID")}</th>
                            <th>${__("Reference #")}</th>
                            <th>${__("Description")}</th>
                            <th class="text-right">${__("Amount")}</th>
                            <th>${__("TR#")}</th>
                        </tr></thead>
                        <tbody>${bankBody}</tbody>
                    </table>
                </div>
            </div>

            <div class="bsr-panel">
                <div class="bsr-panel-title">${__("Unreconciled GL Entries")}</div>
                <div class="bsr-table-wrap">
                    <table class="table table-bordered table-hover bsr-table">
                        <thead><tr>
                            <th>${__("TR#")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Transaction ID")}</th>
                            <th>${__("Reference #")}</th>
                            <th>${__("Description")}</th>
                            <th class="text-right">${__("Amount")}</th>
                        </tr></thead>
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
}

function bsr_bind(frm) {
    const $w = frm.fields_dict.workspace_html.$wrapper;

    $w.find(".bsr-refresh").on("click", () => bsr_load(frm));
    $w.find(".bsr-open-doc").on("click", function (e) {
        e.preventDefault();
        frappe.set_route("Form", $(this).attr("data-doctype"), $(this).attr("data-name"));
    });

    $w.find(".bsr-apply-manual").on("click", () => bsr_apply_manual(frm));
    $w.find(".bsr-save").on("click", () => bsr_save(frm));
}

function bsr_apply_manual(frm) {
    const state = frm.__bsr || {};
    const bankRows = state.bank_rows || [];
    const glRows = state.gl_rows || [];
    const $w = frm.fields_dict.workspace_html.$wrapper;
    const glByTr = {};
    glRows.forEach((row) => { glByTr[String(row.tr_no)] = row; });

    const grouped = {};
    const invalid = [];
    $w.find("tr[data-bank-name]").each(function () {
        const bankName = $(this).attr("data-bank-name");
        const tr = String($(this).find(".bsr-tr-input").val() || "").trim();
        if (!tr) return;
        if (!glByTr[tr]) {
            invalid.push(tr);
            return;
        }
        if (!grouped[tr]) grouped[tr] = [];
        grouped[tr].push(bankName);
    });

    if (invalid.length) {
        frappe.msgprint(__("Unknown GL TR#: {0}", [Array.from(new Set(invalid)).join(", ")]));
        return;
    }
    if (!Object.keys(grouped).length) {
        frappe.msgprint(__("Enter a GL TR# on one or more Bank Statement rows."));
        return;
    }

    const bankByName = {};
    bankRows.forEach((row) => { bankByName[row.name] = row; });
    const tolerance = Math.abs(Number(frm.doc.tolerance || 0.01));
    const newMatches = [];
    const usedBank = new Set();
    const usedGl = new Set();
    const errors = [];

    Object.keys(grouped).forEach((tr) => {
        const gl = glByTr[tr];
        const banks = grouped[tr].map((name) => bankByName[name]).filter(Boolean);
        const bankTotal = bsr_round(banks.reduce((sum, row) => sum + Number(row.amount || 0), 0));
        const glTotal = bsr_round(Number(gl.amount || 0));
        const difference = bsr_round(bankTotal - glTotal);

        if (Math.abs(difference) > tolerance) {
            errors.push(__("TR# {0}: Bank {1}, GL {2}, difference {3}", [
                tr, bsr_money(bankTotal), bsr_money(glTotal), bsr_money(difference),
            ]));
            return;
        }

        newMatches.push({
            match_type: "Manual TR",
            reference_number: banks.map((row) => row.reference_number).find(Boolean) || gl.reference_number || "",
            bank_amount: bankTotal,
            gl_amount: glTotal,
            difference: difference,
            bank_rows: banks,
            gl_rows: [gl],
        });
        banks.forEach((row) => usedBank.add(row.name));
        usedGl.add(gl.name);
    });

    if (errors.length) {
        frappe.msgprint({
            title: __("Manual Links Not Balanced"),
            indicator: "orange",
            message: errors.join("<br>"),
        });
    }

    if (!newMatches.length) return;

    state.matches = (state.matches || []).concat(newMatches);
    state.bank_rows = bankRows.filter((row) => !usedBank.has(row.name));
    state.gl_rows = glRows.filter((row) => !usedGl.has(row.name));
    state.gl_rows.forEach((row, idx) => { row.tr_no = idx + 1; });
    bsr_render(frm);
}

function bsr_save(frm) {
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

function bsr_round(value) {
    return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
}

function bsr_money(value) {
    const number = Number(value || 0);
    return format_currency(number, frappe.defaults.get_default("currency") || "SAR");
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
        .bsr-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start;}
        .bsr-panel{border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:var(--card-bg);padding:10px;min-width:0;}
        .bsr-panel-title{font-weight:600;margin-bottom:8px;}
        .bsr-results{margin-top:12px;}
        .bsr-table-wrap{overflow:auto;max-height:520px;}
        .bsr-table{margin:0;min-width:760px;}
        .bsr-table th,.bsr-table td{font-size:11px;vertical-align:middle !important;white-space:nowrap;}
        .bsr-table .bsr-description{max-width:260px;overflow:hidden;text-overflow:ellipsis;}
        .bsr-tr-input{min-width:62px;text-align:center;}
        @media(max-width:1200px){.bsr-grid{grid-template-columns:1fr;}}
    </style>`;
}
