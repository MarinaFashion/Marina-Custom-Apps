"""Static regression checks for controlled Alhamrani update endpoints.

Run: python marina_custom_apps/pos_reconciliation/tests/check_alhamrani_control.py
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "manual_alhamrani_control_service.py").read_text(encoding="utf-8")
UI = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(encoding="utf-8")
tree = ast.parse(SOURCE)

functions = {
    node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
}
assert {"preview_alhamrani_control", "update_alhamrani_control", "_read",
        "_check_unlinked", "_rrn", "_audit", "_site_guard", "_decide_action"} <= functions.keys()

# Both preview and mutation must enforce permissions, invoice and link checks.
for function in ("preview_alhamrani_control", "update_alhamrani_control"):
    text = ast.get_source_segment(SOURCE, functions[function])
    assert "_site_guard()" in text
    assert "_read(" in text
    assert "_check_unlinked(doc)" in text
    assert "_decide_action(doc)" in text

assert 'meta.has_field("sales_invoice")' in SOURCE
assert 'if not invoice:' in SOURCE
assert 'r"\\d{12}"' in SOURCE
assert 'updates = {"rrn": new_rrn}' in SOURCE
assert '"status": "Approved"' in SOURCE
assert '"response_meaning": MANUAL_SLIP_RESPONSE_MEANING' in SOURCE
assert '_audit(doc,' in SOURCE
assert SOURCE.index('_audit(doc,') < SOURCE.index('frappe.db.set_value(ALHAMRANI_DOCTYPE')
assert '"response_code":' not in SOURCE.split('updates = {')[-1]
assert '"request_json":' not in SOURCE
assert '"response_json":' not in SOURCE
assert "Manual Alhamrani POS Link" in SOURCE
assert "POS Reconciliation Record" in SOURCE
assert 'frappe.db.sql("SELECT name FROM' in SOURCE

assert 'frm.add_custom_button(__("Update Manual Alhamrani Payment"), openAlhamraniControl, __("Actions"));' in UI
assert 'frm.add_custom_button(__("Confirm Manual Alhamrani Payment")' not in UI
assert 'frm.add_custom_button(__("Correct Alhamrani RRN")' not in UI
for label in ("View Records", "Import POS Transactions", "Import Bank Statement",
              "Period Locks", "Execution History"):
    start = UI.index('frm.add_custom_button(__("' + label + '")')
    assert '}, __("Connections"));' in UI[start:start + 350]

assert 'preview_alhamrani_control' in UI
assert 'update_alhamrani_control' in UI
assert 'expected_action:data.action' in UI
assert 'confirmed:1' in UI
assert 'action = _decide_action(doc)' in SOURCE
assert 'if expected_action and cstr(expected_action) != action:' in SOURCE

print("Controlled Alhamrani static regression checks passed.")
