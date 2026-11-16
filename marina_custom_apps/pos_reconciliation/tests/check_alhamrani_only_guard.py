"""Regression checks for managed AUP preview financial evidence classification.

Run: python marina_custom_apps/pos_reconciliation/tests/check_alhamrani_only_guard.py
"""
import ast
from pathlib import Path
from types import SimpleNamespace

service_path = Path(__file__).resolve().parents[1] / "manual_alhamrani_control_service.py"
src = service_path.read_text()
tree = ast.parse(src)
fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_check_unlinked")
code = compile(ast.Module(body=[fn_node], type_ignores=[]), str(service_path), "exec")


class Row(dict):
    def __getattr__(self, key):
        return self.get(key)


class FakeDB:
    def __init__(self, row):
        self.row = row

    def exists(self, doctype, filters=None):
        if doctype == "DocType":
            return True
        if doctype == "Manual Alhamrani POS Link":
            return False
        return True


class FakeFrappe:
    def __init__(self, row):
        self.db = FakeDB(row)
        self.row = row

    def get_all(self, doctype, **kwargs):
        assert doctype == "POS Reconciliation Record"
        assert kwargs["filters"] == {"alhamrani_transaction": "AUP-1"}
        assert kwargs["limit_page_length"] == 0
        return [self.row]

    def throw(self, msg):
        raise ValueError(msg)


def check(**changes):
    row = Row({
        "name": "PREC-1",
        "match_status": "Alhamrani Only",
        "bank_statement_reconciliation": "POS Reconciliation Run",
        "bank_statement_status": "Not Reconciled",
        "accounting_status": "Not Eligible",
    })
    row.update(changes)
    fake = FakeFrappe(row)
    ns = {"frappe": fake, "_": lambda s: s, "cstr": lambda x: "" if x is None else str(x)}
    exec(code, ns)
    ns["_check_unlinked"](SimpleNamespace(name="AUP-1"))


check()  # run-scoped reference must not block an unpaired AUP
for restricted in [
    {"bank_transaction": "BPT-1"},
    {"accounting_posting": "POST-1"},
    {"journal_entry": "ACC-JE-1"},
    {"settlement_number": "SET-1"},
    {"bank_statement_settlement": "SETTLE-1"},
    {"bank_statement_references": "MBST-1"},
    {"bank_statement_status": "Fully Reconciled"},
    {"accounting_status": "Posted"},
    {"match_status": "Fully Matching"},
]:
    try:
        check(**restricted)
    except ValueError:
        pass
    else:
        raise AssertionError("Failed to block protected AUP: " + repr(restricted))
print("Alhamrani Only financial guard checks passed.")
