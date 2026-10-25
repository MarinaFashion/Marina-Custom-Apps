"""Dependency-free tests of the actual Demo bank-settlement unlink guard.

The Frappe database is mocked; settlement/statement records are read-only.
Full transaction integration remains to be verified on Demo after deployment.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

SOURCE = (Path(__file__).resolve().parents[1]
          / "doctype/manual_alhamrani_pos_link/manual_alhamrani_pos_link.py").read_text()


class Dict(dict):
    def __getattr__(self, name):
        return self.get(name)


class Data:
    def __init__(self):
        self.bank = Dict(
            transaction_date="2026-10-25", settled=1,
            settlement_number="SETTLED-1", pos_reconciliation_number="REC-1",
            accounting_status="No Charges", accounting_posting=None, journal_entry=None
        )
        self.record = Dict(
            name="PREC-ABC", record_key="BANK|BPT-1",
            bank_transaction="BPT-1", alhamrani_transaction="AUP-1",
            accounting_status="No Charges", accounting_posting=None, journal_entry=None,
            settlement_number="SETTLED-1", settlement_date="2026-10-25",
            pos_reconciliation_number="REC-1",
            bank_statement_status="Fully Reconciled",
            bank_statement_reconciliation="POS Reconciliation Run",
            bank_statement_settlement="SETTLED-1",
            bank_statement_references="BANK-STATEMENT-1",
        )
        self.settlement = Dict(name="SET-TXN-1", reconciliation_record="PREC-ABC")
        self.posting_item = False
        self.closed = False
        self.queries = []

    def sql(self, query, args):
        assert "FOR UPDATE" in query
        assert args in [("BPT-1",), ("AUP-1",)]
        self.queries.append(("lock", query))

    def get_value(self, doctype, name, fields, as_dict=False):
        assert doctype == "Bank POS Transaction"
        assert name == "BPT-1"
        return self.bank

    def get_all(self, doctype, filters, fields, limit_page_length):
        assert limit_page_length == 25
        if doctype == "POS Reconciliation Record":
            assert filters in [
                {"bank_transaction": "BPT-1"},
                {"alhamrani_transaction": "AUP-1"}
            ]
            return [self.record]
        assert doctype == "POS Bank Settlement Transaction"
        assert filters == {"bank_pos_transaction": "BPT-1"}
        return [self.settlement]

    def exists(self, doctype, filters):
        assert doctype == "POS Accounting Posting Item"
        assert filters in [
            {"bank_transaction": "BPT-1"},
            {"reconciliation_record": "PREC-ABC"}
        ]
        return self.posting_item


data = Data()


def fail(message):
    raise ValueError(str(message))


def check_period(names):
    assert names == ["BPT-1"]
    if data.closed:
        raise ValueError("Finance period Closed")


ns = {
    "frappe": SimpleNamespace(db=data, throw=fail),
    "_": lambda value: value,
    "cstr": lambda value: "" if value is None else str(value),
    "PROTECTED_ACCOUNTING_STATUSES": {
        "Draft Created", "Posted", "Draft - Review Required",
        "Posted - Review Required"
    },
    "assert_bank_transactions_open": check_period,
}
tree = ast.parse(SOURCE)
for name in ("_has_text", "_is_accounting_protected", "_assert_no_financial_dependencies"):
    matched = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name]
    assert len(matched) == 1, name
    node = matched[0]
    # Replace the Frappe import in the production function with our injected
    # check_period dependency; keep the rest of the function unchanged.
    if name == "_assert_no_financial_dependencies":
        node.body = [
            ast.Pass() if isinstance(n, ast.ImportFrom)
            and n.module == "marina_custom_apps.pos_reconciliation.period_control"
            else n for n in node.body
        ]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "<production unlink guard>", "exec"), ns)

run = ns["_assert_no_financial_dependencies"]

# Most relevant case: settled, fully bank-statement reconciled,
# but WITHOUT accounting postings or JEs: permitted.
run("BPT-1", "AUP-1")
assert len(data.queries) == 2

def should_block(reason):
    try:
        run("BPT-1", "AUP-1")
    except ValueError as exc:
        assert reason.lower() in str(exc).lower(), (reason, str(exc))
    else:
        raise AssertionError("Unsafe unlink was accepted: " + reason)

data.bank["accounting_posting"] = "POS-ACC-1"
should_block("commission/VAT")
data.bank["accounting_posting"] = None
data.bank["journal_entry"] = "ACC-JV-1"
should_block("Journal Entry")
data.bank["journal_entry"] = None

data.posting_item = True
should_block("Posting Item")
data.posting_item = False

data.record["accounting_status"] = "Draft Created"
should_block("commission/VAT")
data.record["accounting_status"] = "No Charges"

data.settlement["reconciliation_record"] = "PREC-ANOTHER"
should_block("settlement")
data.settlement["reconciliation_record"] = "PREC-ABC"

data.record["record_key"] = "ALHAMRANI|AUP-1"
should_block("unexpected identity")
data.record["record_key"] = "BANK|BPT-1"

data.closed = True
should_block("Closed")
data.closed = False

run("BPT-1", "AUP-1")
assert "frappe.db.delete(" not in SOURCE
assert "frappe.db.commit(" not in SOURCE
assert "rollback_enrichment(self)" in SOURCE
print("Settled/no-posting unlink guard and financial reference protection passed")
