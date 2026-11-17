"""Standalone regression checks for Marina Send Stock transit initialization.

Run: python marina_custom_apps/stock_transfer_control/tests/check_send_stock_transit.py
Does not connect to a site or write stock/accounting data.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "stock_entry_events.py").read_text(encoding="utf-8")
JS = (ROOT.parent / "public/js/stock_entry_control.js").read_text(encoding="utf-8")
END_TRANSIT = (ROOT / "end_transit.py").read_text(encoding="utf-8")
tree = ast.parse(SOURCE)

fn = next(
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name == "_ensure_send_stock_transit"
)
module = ast.Module(body=[fn], type_ignores=[])
ns = {
    "TYPE_SEND_STOCK": "Send Stock",
    "TYPE_RECEIVE_STOCK": "Receive Stock",
    "TYPE_TRANSFER_BETWEEN": "Transfer Between",
    "_has_mr_origin": lambda doc: doc.mr_origin,
}
exec(compile(module, "<transit>", "exec"), ns)
ensure = ns["_ensure_send_stock_transit"]


def check(stock_entry_type, docstatus, mr_origin, initial, expected):
    doc = SimpleNamespace(
        stock_entry_type=stock_entry_type,
        docstatus=docstatus,
        mr_origin=mr_origin,
        add_to_transit=initial,
    )
    ensure(doc)
    assert doc.add_to_transit == expected, (stock_entry_type, docstatus, mr_origin, initial, doc.add_to_transit)


# New and draft Send Stock must use ERPNext's standard transfer lifecycle.
check("Send Stock", 0, False, 0, 1)
check("Send Stock", 0, True, 0, 1)
check("Material Transfer", 0, True, 0, 1)
check("Send Stock", 0, False, 1, 1)

# Never rewrite already submitted/cancelled stock-ledger evidence.
check("Send Stock", 1, False, 0, 0)
check("Send Stock", 2, False, 0, 0)

# No change to Receive Stock, Transfer Between or unrelated ERPNext types.
check("Receive Stock", 0, True, 0, 0)
check("Transfer Between", 0, True, 0, 0)
check("Material Issue", 0, False, 0, 0)

assert "_ensure_send_stock_transit(doc)" in SOURCE
assert "doc.add_to_transit = 1" in SOURCE
assert "async function marina_ensure_standard_transit(frm)" in JS
assert 'frm.doc.docstatus === 0 && !frm.doc.add_to_transit' in JS
assert 'await frm.set_value("add_to_transit", 1);' in JS
assert 'await frm.set_value("add_to_transit", 0);' not in JS
assert "marina_disable_standard_transit" not in JS
assert '!!frm.doc.add_to_transit' in JS
assert "if not send.add_to_transit:" in END_TRANSIT

print("Marina Send Stock Add to Transit checks passed.")
