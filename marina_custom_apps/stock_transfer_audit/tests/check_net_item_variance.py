"""Dependency-free regression tests for netting duplicate Stock Transfer Audit SKUs.

Run from repository root:
    python marina_custom_apps/stock_transfer_audit/tests/check_net_item_variance.py
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def extract(path, name, cls=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = tree.body
    if cls:
        body = next(n.body for n in body if isinstance(n, ast.ClassDef) and n.name == cls)
    node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec")


def flt(value):
    return float(value or 0)


class Row(dict):
    __getattr__ = dict.get


class FakeDoc:
    def __init__(self, **data):
        self.__dict__.update(data)

    def get(self, key):
        return getattr(self, key, None)


class Frappe:
    def get_doc(self, doctype, name):
        assert doctype == "Stock Entry"
        return docs[name]

    def throw(self, message):
        raise AssertionError(message)


docs = {
    "SEND": FakeDoc(
        name="SEND", docstatus=1, stock_entry_type="Send Stock",
        posting_date="2026-11-17", from_warehouse="Source",
        to_warehouse="Transit", custom_intended_final_warehouse="Target",
        items=[],
    ),
    "RECEIVE": FakeDoc(
        name="RECEIVE", docstatus=1, stock_entry_type="Receive Stock",
        outgoing_stock_entry="SEND", posting_date="2026-11-17",
        to_warehouse="Target",
        items=[
            Row(name="row1", item_code="SKU-A", qty=1, custom_actual_received_qty=2, ste_detail="send1"),
            Row(name="row2", item_code="SKU-A", qty=1, custom_actual_received_qty=0, ste_detail="send2"),
            Row(name="row3", item_code="SKU-B", qty=1, custom_actual_received_qty=0, ste_detail="send3"),
        ],
        custom_unexpected_received_items=[],
    ),
}

ns = {
    "frappe": Frappe(),
    "_": lambda value: value,
    "flt": flt,
    "SEND_TYPE": "Send Stock",
    "RECEIVE_TYPE": "Receive Stock",
    "_submitted_receive_for_send": lambda name: "RECEIVE",
}
exec(extract(ROOT / "audit_service.py", "get_transfer_snapshot"), ns)
snapshot = ns["get_transfer_snapshot"]("SEND")
by_item = {row["item_code"]: row for row in snapshot["items"]}
assert len(snapshot["items"]) == 2, snapshot
assert by_item["SKU-A"]["sent_qty"] == 2
assert by_item["SKU-A"]["actual_received_qty"] == 2
assert by_item["SKU-A"]["discrepancy_qty"] == 0
assert by_item["SKU-A"]["send_stock_detail"] is None
assert by_item["SKU-A"]["receive_stock_detail"] is None
assert by_item["SKU-B"]["discrepancy_qty"] == 1
assert snapshot["total_sent_qty"] == 3
assert snapshot["total_received_qty"] == 2
assert snapshot["total_variance_qty"] == 1
assert snapshot["total_abs_variance_qty"] == 1

for name in ("stock_transfer_audit_record", "status_service"):
    path = (ROOT / "doctype/stock_transfer_audit_record/stock_transfer_audit_record.py"
            if name == "stock_transfer_audit_record" else ROOT / "status_service.py")
    if name == "stock_transfer_audit_record":
        globals_ = {
            "flt": flt, "ACTION_IGNORE": "Ignore",
            "ACTION_MOVE_TO_SOURCE": "Move to Source",
            "ACTION_MOVE_TO_TARGET": "Move to Target",
            "frappe": Frappe(), "_": lambda value: value,
        }
        exec(extract(path, "_correction_groups", "StockTransferAuditRecord"), globals_)
        groups = globals_["_correction_groups"](FakeDoc(items=[
            Row(item_code="SKU-A", discrepancy_qty=-1, action="Move to Target"),
            Row(item_code="SKU-A", discrepancy_qty=1, action="Move to Source"),
            Row(item_code="SKU-B", discrepancy_qty=2, action="Move to Source"),
        ]))
        assert groups == {"to_source": {"SKU-B": 2}, "to_target": {}}, groups

print("Stock Transfer Audit net-item regression checks passed.")
