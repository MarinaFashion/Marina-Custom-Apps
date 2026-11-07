frappe.ui.form.on("Marina Bank Statement Import", {
    refresh(frm) {
        if (frm.is_new()) return;

        const importing = frm.doc.status === "Importing";
        if (importing) {
            frm.set_intro(__("Statement import is running in the background."), "blue");
            marina_statement_poll(frm);
            return;
        }

        if (frm.doc.import_file && ["Draft", "Validated", "Completed with Errors", "Failed"].includes(frm.doc.status || "Draft")) {
            frm.add_custom_button(__("Validate Statement"), () => marina_statement_validate(frm));
            const btn = frm.add_custom_button(__("Import Statement"), () => marina_statement_import(frm));
            btn.addClass("btn-primary");
        }

        frm.add_custom_button(__("Statement Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction", {statement_import: frm.doc.name});
        }, __("View"));
        frm.add_custom_button(__("Unreconciled Transactions"), () => {
            frappe.set_route("List", "Marina Bank Statement Transaction", {
                statement_import: frm.doc.name,
                reconciliation_status: "Unreconciled",
            });
        }, __("View"));
    },
});

function marina_statement_validate(frm) {
    return frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.validate_statement",
        args: {name: frm.doc.name},
        freeze: true,
        freeze_message: __("Validating SNB statement..."),
    }).then((r) => {
        const s = r.message || {};
        frappe.msgprint({
            title: __("Statement Validation"),
            indicator: cint(s.error_records || 0) || cint(s.review_warning_records || 0) ? "orange" : "green",
            message: __("Rows: {0}<br>New: {1}<br>Duplicates skipped: {2}<br>POS lines: {3}<br>Other lines: {4}<br>Errors: {5}<br>Possible duplicates requiring review: {6}", [
                s.total_rows || 0, s.new_records || 0, s.duplicate_records || 0,
                s.pos_statement_lines || 0, s.other_statement_lines || 0, s.error_records || 0,
                s.review_warning_records || 0
            ]),
        });
        return frm.reload_doc();
    });
}


function marina_statement_import(frm) {
    // The server revalidates the XLSX and current bank ledger before presenting
    // any decisions. Every warning defaults to Skip; no silent approval.
    return frappe.call({
        method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.get_statement_duplicate_review",
        args: {name: frm.doc.name},
        freeze: true,
        freeze_message: __("Checking bank statement for duplicates..."),
    }).then((r) => frm.reload_doc().then(() => {
        const payload = r.message || {};
        marina_statement_open_duplicate_review(frm, payload);
    }));
}

function marina_statement_open_duplicate_review(frm, payload) {
    const candidates = (payload.candidates || []).map((item) => ({
        ...item,
        selected: false,
        action: "skip", // Conservative default: import no possible duplicate without review.
    }));
    const exact = (payload.exact_duplicate_rows || []).length;
    const summary = payload.summary || {};
    const esc = (value) => $("<div>").text(String(value ?? "")).html();
    let page = 0;
    const pageSize = 75;
    const totals = () => {
        const approved = candidates.filter((item) => item.action === "import").length;
        const skipped = candidates.length - approved;
        const ready = Math.max(0, cint(summary.new_records || 0) - exact - skipped);
        return {approved, skipped, ready};
    };
    const enqueue = () => {
        const decisions = Object.fromEntries(
            candidates.map((item) => [String(item.row_number), item.action])
        );
        return frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.start_statement_import",
            args: {
                name: frm.doc.name,
                review_decisions: JSON.stringify(decisions),
                expected_review_token: payload.review_token,
            },
            freeze: true,
            freeze_message: __("Queueing reviewed statement import..."),
        }).then(() => frm.reload_doc().then(() => marina_statement_poll(frm)));
    };
    if (!candidates.length) {
        const ready = Math.max(0, cint(summary.new_records || 0) - exact);
        frappe.confirm(
            __("Import {0} new transactions? {1} exact financial duplicates will be automatically skipped.", [ready, exact]),
            () => enqueue()
        );
        return;
    }

    const dialog = new frappe.ui.Dialog({
        title: __("Review Possible Bank Statement Duplicates"),
        size: "extra-large",
        fields: [{fieldname: "duplicate_review_html", fieldtype: "HTML"}],
        primary_action_label: __("Import Reviewed Statement"),
        primary_action() {
            const values = totals();
            frappe.confirm(
                __("Final import decision: import {0} new transactions (including {1} reviewed possible duplicates), skip {2} possible duplicates and {3} exact duplicates. Confirm?", [
                    values.ready, values.approved, values.skipped, exact
                ]),
                () => enqueue().then(() => dialog.hide())
            );
        },
    });

    const render = () => {
        const count = candidates.length;
        const pages = Math.max(1, Math.ceil(count / pageSize));
        page = Math.max(0, Math.min(page, pages - 1));
        const offset = page * pageSize;
        const current = candidates.slice(offset, offset + pageSize);
        const {approved, skipped, ready} = totals();
        const selected = candidates.filter((item) => item.selected).length;
        const $host = dialog.fields_dict.duplicate_review_html.$wrapper;
        $host.html(`
          <div class="small text-muted" style="margin-bottom:10px">
            ${__("Possible duplicates are set to Skip by default. Select individual rows or Select All, then use a bulk action. You may change any row's action afterwards.")}
          </div>
          <div class="alert alert-info" style="padding:10px;margin-bottom:12px">
            <b>${__("Expected to import")}: ${ready}</b>
            &nbsp; | &nbsp; ${__("Possible duplicates to import")}: ${approved}
            &nbsp; | &nbsp; ${__("Possible duplicates to skip")}: ${skipped}
            &nbsp; | &nbsp; ${__("Exact duplicates automatically skipped")}: ${exact}
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
            <label style="margin:0"><input type="checkbox" class="marina-review-select-all"
              ${selected===count?"checked":""}> ${__("Select All")} (${count})</label>
            <span class="text-muted small">${__("Selected")}: ${selected}</span>
            <button class="btn btn-default btn-xs marina-review-bulk-skip">${__("Skip Selected")}</button>
            <button class="btn btn-default btn-xs marina-review-bulk-import">${__("Import Selected")}</button>
          </div>
          <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
            <table class="table table-bordered table-hover" style="margin-bottom:4px">
              <thead><tr>
                <th style="width:32px">${__("Select")}</th>
                <th>${__("Excel Row")}</th><th>${__("Date")}</th>
                <th>${__("Reference")}</th><th class="text-right">${__("Debit")}</th>
                <th class="text-right">${__("Credit")}</th><th class="text-right">${__("Balance")}</th>
                <th>${__("Possible Duplicate Of")}</th><th style="min-width:105px">${__("Action")}</th>
              </tr></thead>
              <tbody>
                ${current.map((item, pageIdx) => {
                    const idx = offset + pageIdx;
                    const note = String(item.message || "");
                    const counterpart = note.match(/Possible duplicate of ([^:]+):/);
                    return `<tr>
                      <td><input type="checkbox" class="marina-review-selected" data-index="${idx}" ${item.selected?"checked":""}></td>
                      <td>${esc(item.row_number)}</td>
                      <td>${esc(item.processing_date)}</td>
                      <td>${esc(item.reference_number)}</td>
                      <td class="text-right">${Number(item.debit || 0).toFixed(2)}</td>
                      <td class="text-right">${Number(item.credit || 0).toFixed(2)}</td>
                      <td class="text-right">${Number(item.balance || 0).toFixed(2)}</td>
                      <td title="${esc(note)}">${esc(counterpart ? counterpart[1] : note)}</td>
                      <td><select class="form-control input-xs marina-review-row-action" data-index="${idx}">
                        <option value="skip" ${item.action==="skip"?"selected":""}>${__("Skip")}</option>
                        <option value="import" ${item.action==="import"?"selected":""}>${__("Import")}</option>
                      </select></td>
                    </tr>`;
                }).join("")}
              </tbody>
            </table>
          </div>
          <div style="display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:8px">
            <span class="text-muted small">${__("Page")} ${page+1} / ${pages}</span>
            <button class="btn btn-default btn-xs marina-review-prev" ${page===0?"disabled":""}>${__("Previous")}</button>
            <button class="btn btn-default btn-xs marina-review-next" ${page>=pages-1?"disabled":""}>${__("Next")}</button>
          </div>
        `);
        $host.find(".marina-review-select-all").on("change", function () {
            candidates.forEach((item) => {item.selected = $(this).prop("checked");});
            render();
        });
        $host.find(".marina-review-selected").on("change", function () {
            candidates[Number($(this).attr("data-index"))].selected = $(this).prop("checked");
            render();
        });
        $host.find(".marina-review-row-action").on("change", function () {
            const selectedAction = $(this).val();
            if (!["skip", "import"].includes(selectedAction)) return;
            candidates[Number($(this).attr("data-index"))].action = selectedAction;
            render();
        });
        for (const [selector, action] of [
            [".marina-review-bulk-skip", "skip"],
            [".marina-review-bulk-import", "import"]
        ]) {
            $host.find(selector).on("click", () => {
                if (!candidates.some((item) => item.selected)) {
                    frappe.msgprint(__("Select one or more transactions first."));
                    return;
                }
                candidates.forEach((item) => {if (item.selected) item.action = action;});
                render();
            });
        }
        $host.find(".marina-review-prev").on("click", () => {page -= 1; render();});
        $host.find(".marina-review-next").on("click", () => {page += 1; render();});
    };
    dialog.show();
    render();
}

function marina_statement_poll(frm) {
    if (frm.__marina_statement_polling) return;
    frm.__marina_statement_polling = true;
    const poll = () => {
        frappe.call({
            method: "marina_custom_apps.pos_reconciliation.doctype.marina_bank_statement_import.marina_bank_statement_import.get_status",
            args: {name: frm.doc.name},
        }).then((r) => {
            const s = r.message || {};
            if (s.status === "Importing") {
                setTimeout(poll, 2000);
                return;
            }
            frm.__marina_statement_polling = false;
            frm.reload_doc().then(() => {
                frappe.msgprint({
                    title: __("Statement Import Finished"),
                    indicator: s.status === "Completed" ? "green" : "orange",
                    message: __("Status: {0}<br>Inserted: {1}<br>Duplicates: {2}<br>Errors: {3}", [
                        s.status || "", s.inserted_records || 0, s.duplicate_records || 0, s.error_records || 0
                    ]),
                });
            });
        }).catch(() => { frm.__marina_statement_polling = false; });
    };
    setTimeout(poll, 1200);
}
