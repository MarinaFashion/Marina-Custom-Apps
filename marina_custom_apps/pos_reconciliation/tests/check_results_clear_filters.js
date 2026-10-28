"use strict";

// Dependency-free test of the production POS Results "Clear" click handler.
// Run: node marina_custom_apps/pos_reconciliation/tests/check_results_clear_filters.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
    path.join(__dirname, "../doctype/pos_reconciliation_run/pos_reconciliation_run.js"),
    "utf8"
);
assert.equal(source.includes(
    "Primary match remains Terminal ID + RRN + Auth Code + Transaction Type."
), false, "The explanatory matching paragraph must not appear above results");

const start = source.indexOf("function pos_recon_bind_result_filters(");
const end = source.indexOf("\nfunction pos_recon_bind_search(", start);
assert.ok(start >= 0 && end > start, "Production result-filter handler must exist");
const production = source.slice(start, end);

const handlers = {};
let pendingTimer = null;
const clearedTimers = [];
const requests = [];
const renders = [];
const state = {
    status: "All Pending",
    from_date: "2026-10-04",
    to_date: "2026-10-18",
    settlement_number: ["SET-01"],
    settlement_date: "2026-10-15",
    pos_profile: ["POS01"],
    terminal_id: ["TERM01"],
    card_type: "Mada",
    response_meaning: "Confirmed manually from terminal slip",
    ledger_posting_status: "Pending",
    accounting_status: "Pending",
    before_integration: "1",
    start: 25,
    search: "example",  // Search is separate from the filter panel.
};
const frm = {
    doc: {from_date: "2026-10-01", to_date: "2026-10-31"},
    __pos_recon_review: {results: state},
};

const wrapper = {
    off() { return this; },
    on(event, selector, callback) {
        handlers[event] = callback;
        return this;
    },
    find(selector) {
        return {on(event, callback) { handlers[selector] = callback; return this; }};
    },
};

const context = {
    clearTimeout(id) {clearedTimers.push(id);},
    setTimeout(callback, delay) {
        assert.equal(delay, 150);
        pendingTimer = 735;
        return pendingTimer;
    },
    pos_recon_read_controls() {return {response_meaning: state.response_meaning};},
    pos_recon_load_filter_options(_frm, draft) {
        requests.push({response: state.response_meaning, draft});
        return Promise.resolve({});
    },
    pos_recon_update_cascade() {},
    pos_recon_load_results(_frm) {
        renders.push(JSON.parse(JSON.stringify(state)));
        return Promise.resolve();
    }
};
vm.createContext(context);
vm.runInContext(production, context);
context.pos_recon_bind_result_filters(frm, wrapper, null, false, true);

async function test() {
    assert.equal(typeof handlers[".pos-recon-clear-bank-filters"], "function");
    // Mimic an outstanding cascading-filter refresh, then press Clear.
    handlers["change.posreconfilters"]();
    assert.equal(pendingTimer, 735);
    handlers[".pos-recon-clear-bank-filters"]();
    await new Promise((resolve) => setImmediate(resolve));

    assert.ok(clearedTimers.includes(735), "Clear must cancel pending filter-option debounce");
    assert.equal(requests.length, 1, "Clear should fetch fresh unfiltered options once");
    assert.equal(requests[0].response, "", "Filter request must not retain Response Meaning");
    assert.equal(renders.length, 1, "Clear should reload results exactly once");
    assert.deepEqual(renders[0], {
        status: "All Pending",   // Status pills are outside the filter panel.
        from_date: "2026-10-01",
        to_date: "2026-10-31",
        settlement_number: [],
        settlement_date: "",
        pos_profile: [],
        terminal_id: [],
        card_type: "",
        response_meaning: "",
        ledger_posting_status: "",
        accounting_status: "",
        before_integration: "All",
        start: 0,
        search: "example"
    });
    assert.equal(
        source.includes('state.response_meaning==="Confirmed manually from terminal slip"?"selected":""'),
        true,
        "Re-rendering an empty Response Meaning selection must display All"
    );
    console.log("Results header removal and Clear filter state regression checks passed.");
}
test().catch((error) => {console.error(error); process.exitCode = 1;});
