"use strict";

// Dependency-free tests for the unsaved manual Match # preview.
// Run: node marina_custom_apps/pos_reconciliation/tests/check_bank_reconciliation_live_preview.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const src = fs.readFileSync(
    path.join(__dirname, "../doctype/bank_statement_reconciliation/bank_statement_reconciliation.js"),
    "utf8"
);

function extract(name, nextName) {
    const start = src.indexOf("function " + name + "(");
    assert.ok(start >= 0, "Missing function: " + name);
    const end = src.indexOf("\nfunction " + nextName + "(", start);
    assert.ok(end > start, "Missing next function: " + nextName);
    return src.slice(start, end);
}

const ctx = {
    bsr_round: x => Math.round((Number(x) + Number.EPSILON) * 100) / 100,
    bsr_money: x => "SR " + Number(x || 0).toFixed(2),
    bsr_escape: x => String(x || "").replace(/&/g, "&amp;").replace(/</g, "&lt;"),
    __: x => x,
};
vm.createContext(ctx);
vm.runInContext(
    extract("bsr_preview_manual_matches", "bsr_preview_rows_html") +
    extract("bsr_preview_rows_html", "bsr_update_results_preview"),
    ctx
);
const preview = ctx.bsr_preview_manual_matches;
const bank = (group_no, amount, name) => ({group_no, amount, name, reference_number: "REF"});
const gl = (group_no, amount, name) => ({group_no, amount, name, reference_number: "REF"});
const toPlain = value => JSON.parse(JSON.stringify(value));

let results = toPlain(preview([bank("1001", -100, "B1")], [], 0.01));
assert.equal(results[0].preview_status, "Incomplete");
assert.equal(results[0].bank_amount, -100);
assert.equal(results[0].gl_amount, 0);
assert.equal(results[0].bank_rows.length, 1);
assert.equal(results[0].gl_rows.length, 0);

results = toPlain(preview([bank("1001", -100, "B1")], [gl("1001", -97, "G1")], 0.01));
assert.equal(results[0].preview_status, "Difference");
assert.equal(results[0].difference, -3);

results = toPlain(preview(
    [bank("1001", -60, "B1"), bank("1001", -40, "B2")],
    [gl("1001", -100, "G1")], 0.01
));
assert.equal(results[0].preview_status, "Balanced");
assert.equal(results[0].bank_rows.length, 2);
assert.equal(results[0].gl_rows.length, 1);
assert.equal(results[0].difference, 0);

results = toPlain(preview([bank("123", 25, "B1"), bank("1001", 50, "B2")], [], 0.01));
assert.deepEqual(results.map(x => x.group_no), ["123", "1001"]);
assert.equal(toPlain(preview([], [], 0.01)).length, 0);
assert.equal(toPlain(preview([bank("0", 10, "B1")], [gl("0", 10, "G1")], 0.01))[0].preview_status, "Invalid Match #");

const html = ctx.bsr_preview_rows_html(toPlain(preview([bank("1001", -100)], [], 0.01)));
assert.ok(html.includes('data-preview-match="1001"'));
assert.ok(html.includes("Incomplete"));
assert.ok(!html.includes("Ready to Save"));
assert.ok(ctx.bsr_preview_rows_html([]).includes("No matches prepared yet."));

assert.ok(src.includes("bsr_update_results_preview(frm);"), "Input listener must refresh preview");
assert.ok(src.includes('class="bsr-preview-body"'), "Preview tbody must be updated without full re-render");
assert.ok(src.includes('class="bsr-prepared-count"'), "Prepared group counter must be updated");
assert.ok(src.includes("bsr_build_manual_matches(bankRows, glRows, frm.doc.tolerance"), "Save validation must remain intact");
assert.ok(src.includes("bank_names: (match.bank_rows || []).map((row) => row.name)"), "Save payload must remain intact");
console.log("Live Match # preview: incomplete, difference, balanced, many-to-one, invalid, and save guards passed.");
