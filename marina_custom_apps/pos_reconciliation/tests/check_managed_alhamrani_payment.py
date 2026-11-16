"""Standalone regression checks for guided AUP management.

Run: python marina_custom_apps/pos_reconciliation/tests/check_managed_alhamrani_payment.py
No database or Frappe installation is needed for these workflow checks.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "managed_alhamrani_payment_service.py").read_text(encoding="utf-8")
UI = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(encoding="utf-8")
tree = ast.parse(SOURCE)


def extract(name, namespace):
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    node.decorator_list = []
    code = compile(ast.Module(body=[node], type_ignores=[]), "<managed>", "exec")
    exec(code, namespace)
    return namespace[name]


class Attr(dict):
    __getattr__ = dict.get


class Doc:
    def __init__(self, status, rrn, manual=False):
        self.name = "AUP-2026-00001"
        self.data = {
            "status": status, "rrn": rrn,
            "response_meaning": "manual" if manual else "",
        }

    def get(self, name):
        return self.data.get(name)


def test_preview():
    import re
    from types import SimpleNamespace

    def build(status="Approved", rrn="111111111111", manual=True, linked=None, record=None):
        calls = []
        doc = Doc(status, rrn, manual)
        source = Attr(
            name=doc.name, rrn=rrn, amount=369,
            transaction_date="2026-11-12", transaction_time="17:08:19",
            pos_profile="P1",
        )
        ns = {
            "_source": lambda name: (doc, "INV-1", None, source),
            "_related_records": lambda name: (linked, record),
            "_check_unlinked": lambda doc: calls.append("checked"),
            "_is_manual": lambda doc: manual,
            "_decide_action": lambda doc: "confirm",
            "_rrn": lambda rrn: rrn if re.fullmatch(r"\d{12}", rrn) else (_ for _ in ()).throw(ValueError()),
            "_candidates": lambda source, rrn: [{"name": "BPT-1"}],
            "re": re, "cstr": str,
        }
        return extract("_preview", ns), calls

    preview, calls = build()
    assert preview("AUP-2026-00001")["state"] == "ready_to_link"
    assert preview("AUP-2026-00001")["candidates"][0]["name"] == "BPT-1"
    assert calls == ["checked"]

    preview, _ = build(rrn="", manual=True)
    assert preview("AUP-2026-00001")["state"] == "needs_rrn_correction"
    assert preview("AUP-2026-00001", "222222222222")["state"] == "needs_rrn_correction"

    preview, _ = build(status="Pending", manual=False, rrn="")
    assert preview("AUP-2026-00001")["state"] == "needs_confirmation"

    preview, _ = build(status="Approved", manual=False)
    assert preview("AUP-2026-00001")["state"] == "ready_to_link"

    preview, _ = build(linked=Attr(name="LINK-1", status="Approved", bank_pos_transaction="BPT-1"))
    assert preview("AUP-2026-00001")["state"] == "already_linked"

    preview, _ = build(record=Attr(name="PREC-1", bank_transaction="BPT-1", match_status="Fully Matching"))
    assert preview("AUP-2026-00001")["state"] == "already_matched"


def test_atomic_endpoint_structure():
    assert "frappe.db.commit(" not in SOURCE
    assert "frappe.db.delete(" not in SOURCE
    assert "update_alhamrani_control(" in SOURCE
    assert "approve_manual_link(" in SOURCE
    assert SOURCE.index("update_alhamrani_control(") < SOURCE.index("approve_manual_link(")
    assert "FOR UPDATE" in SOURCE
    assert "selected Bank POS" in SOURCE
    assert "expected_state" in SOURCE
    assert "confirm_mapping" in SOURCE
    assert "No change requested" in SOURCE


def test_single_ui_and_guarded_confirmation():
    assert UI.count('add_custom_button(__("Manage Alhamrani Payment")') == 1
    assert 'add_custom_button(__("Link Manual Alhamrani Payment")' not in UI
    assert 'add_custom_button(__("Update Manual Alhamrani Payment")' not in UI
    assert '"preview_managed_alhamrani_payment"' in UI
    assert '"apply_managed_alhamrani_payment"' in UI
    assert "pos_recon_manual_link_preview(candidate)" in UI
    assert 'dialog.set_value("confirm_mapping", 0)' in UI
    assert "rrn !== searchedRRN" in UI
    assert 'expected_state:proposed.state' in UI
    assert "profilesDiffer" not in UI  # new path uses profileWarning


if __name__ == "__main__":
    test_preview()
    test_atomic_endpoint_structure()
    test_single_ui_and_guarded_confirmation()
    print("Guided Alhamrani payment checks passed.")
