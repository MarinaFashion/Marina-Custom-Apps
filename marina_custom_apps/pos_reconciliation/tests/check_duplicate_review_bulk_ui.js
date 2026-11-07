"use strict";

// Test actual imported function with a lightweight Frappe/jQuery dialog harness.
// Run: node marina_custom_apps/pos_reconciliation/tests/check_duplicate_review_bulk_ui.js
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const source = fs.readFileSync(
    path.join(__dirname, "../doctype/marina_bank_statement_import/marina_bank_statement_import.js"),
    "utf8"
);
const start = source.indexOf("function marina_statement_open_duplicate_review(");
const end = source.indexOf("\nfunction marina_statement_poll(", start);
assert.ok(start >= 0 && end > start, "Duplicate review dialog must exist.");
const code = source.slice(start, end);
assert.ok(code.includes('action: "skip"'), "Possible duplicates must default to Skip");

let dialog = null;
let markup = "";
let handlers = {};
let payloadSent = null;
let messages = [];

const host = {
    html(value) {
        markup = value;
        handlers = {};
        return this;
    },
    find(selector) {
        return {
            on(event, fn) {
                handlers[selector] = fn;
                return this;
            }
        };
    }
};
class Dialog {
    constructor(opts) {
        this.opts = opts;
        this.fields_dict = {duplicate_review_html: {$wrapper: host}};
        dialog = this;
    }
    show() {this.visible = true;}
    hide() {this.visible = false;}
}
function $(input) {
    if (input === "<div>") {
        return {
            text(value) {
                return {
                    html() {return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");}
                };
            }
        };
    }
    return {
        prop(name) {assert.equal(name, "checked"); return input.checked;},
        attr(name) {assert.equal(name, "data-index"); return input.idx;},
        val() {return input.value;}
    };
}
const calls = [];
const context = {
    $,
    cint(value) {return Number(value || 0) || 0;},
    __(str, vars) {
        return vars ? str.replace(/\{(\d+)\}/g, (_, n) => String(vars[Number(n)])) : str;
    },
    frappe: {
        ui: {Dialog},
        confirm(message, callback) {messages.push(message);callback();},
        msgprint(value) {messages.push(value);},
        call(request) {
            calls.push(request);
            payloadSent = request.args;
            return Promise.resolve({message: {queued: 1}});
        }
    },
    marina_statement_poll() {}
};
vm.createContext(context);
vm.runInContext(code, context);

const frm = {
    doc: {name: "MBS-IMP-TEST"},
    reload_doc() {return Promise.resolve();}
};
const candidates = Array.from({length: 78}, (_, i) => ({
    row_number: 13 + i,
    source_key: "MBST-" + i,
    processing_date: "2026-10-31",
    reference_number: "R-" + i,
    debit: 100,
    credit: 0,
    balance: i,
    message: "Possible duplicate of MBST-ORIGINAL: review."
}));
const payload = {
    candidates,
    review_token: "REVIEW-TOKEN",
    exact_duplicate_rows: [10],
    summary: {new_records: 82},
};
context.marina_statement_open_duplicate_review(frm, payload);
assert.ok(dialog.visible);
assert.ok(markup.includes("Select All"));
assert.ok(markup.includes('option value="skip" selected'));
assert.ok(markup.includes("Expected to import"));
assert.ok(markup.includes("Possible duplicates to skip"));
assert.ok(markup.includes("Page 1 / 2"));

handlers[".marina-review-select-all"].call({checked: true});
assert.ok(markup.includes("Selected</span>") || markup.includes("Selected: 78"));
handlers[".marina-review-bulk-import"]();
assert.ok(markup.includes('option value="import" selected'));
assert.ok(markup.includes("Page 1 / 2"));

handlers[".marina-review-next"]();
assert.ok(markup.includes("Page 2 / 2"));
assert.ok(markup.includes("R-77"));

handlers[".marina-review-prev"]();
handlers[".marina-review-row-action"].call({idx: 0, value: "skip"});
assert.ok(markup.includes('option value="skip" selected'));

async function run() {
    dialog.opts.primary_action();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(payloadSent.name, "MBS-IMP-TEST");
    assert.equal(payloadSent.expected_review_token, "REVIEW-TOKEN");
    const decisions = JSON.parse(payloadSent.review_decisions);
    assert.equal(Object.keys(decisions).length, 78);
    assert.equal(decisions["13"], "skip", "Individual decisions must override bulk choices");
    assert.equal(decisions["14"], "import");
    assert.equal(decisions["90"], "import", "Select All must cover pages not yet rendered");
    assert.ok(messages.some((text) => text.includes("import 80 new transactions")));
    assert.equal(dialog.visible, false);
    console.log("Bulk Select All, conservative default Skip, per-row override and 78-row review passed.");
}
run().catch((error) => {console.error(error);process.exitCode = 1;});
