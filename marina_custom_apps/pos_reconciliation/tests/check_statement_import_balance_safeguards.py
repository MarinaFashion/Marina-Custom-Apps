"""Dependency-free regression checks for SNB statement import safeguards.

Run: python marina_custom_apps/pos_reconciliation/tests/check_statement_import_balance_safeguards.py
"""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "marina_bank_statement_import_service.py").read_text(encoding="utf-8")
UI = (ROOT / "doctype/marina_bank_statement_import/marina_bank_statement_import.js").read_text(encoding="utf-8")
WRAPPER = (ROOT / "doctype/marina_bank_statement_import/marina_bank_statement_import.py").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "doctype/marina_bank_statement_import/marina_bank_statement_import.json").read_text(encoding="utf-8"))
TREE = ast.parse(SOURCE)
FUNCTIONS = {node.name: node for node in TREE.body if isinstance(node, ast.FunctionDef)}


def extracted(*names, env):
    source = [FUNCTIONS[n] for n in names]
    compiled = compile(ast.Module(body=source, type_ignores=[]), "real_statement_import_functions", "exec")
    exec(compiled, env)
    return env


def cstr(value):
    return "" if value is None else str(value)


def flt(value, digits=2):
    return round(float(value or 0), digits)


class AttrDict(dict):
    def __getattr__(self, key):
        return self.get(key)


class FakeFrappe:
    def __init__(self):
        self.prior = []
        self.calls = []
        self.enqueued = []
        self.session = SimpleNamespace(user="accounts@example.com")

    def throw(self, message):
        raise ValueError(message)

    def get_all(self, doctype, filters=None, pluck=None, **kwargs):
        self.calls.append((doctype, filters, kwargs))
        if pluck == "source_key":
            return []
        assert doctype == "Marina Bank Statement Transaction"
        assert filters["bank_account"] == "SNB"
        assert "processing_date" in filters and "reference_number" in filters
        return [
            AttrDict(x) for x in self.prior
            if x["processing_date"] == filters["processing_date"]
            and x["reference_number"] in filters["reference_number"][1]
        ]

    def get_doc(self, doctype, name):
        return self.doc

    def enqueue(self, *args, **kwargs):
        self.enqueued.append(kwargs)


fake = FakeFrappe()
sheet = {"rows": []}
headers = {
    "processingdate": "processing_date",
    "description": "description",
    "debit": "debit",
    "credit": "credit",
    "balance": "balance",
    "reference": "reference_number",
}
env = {
    "frappe": fake,
    "_": lambda text: text,
    "cstr": cstr,
    "flt": flt,
    "cint": lambda value: int(value or 0),
    "re": re,
    "TXN_DOCTYPE": "Marina Bank Statement Transaction",
    "HEADER_LOOKUP": headers,
    "CHUNK": 500,
    "read_xlsx_file_from_attached_file": lambda **kwargs: sheet["rows"],
    "_file_content": lambda _: b"xlsx-content",
}
extracted("_normalize_header", "_cell", "_read_rows",
          "_financial_identity", "_secondary_financial_identity",
          "_prior_financial_duplicates", env=env)

base_header = ["Processing Date", "Description", "Debit", "Credit", "Balance", "Reference"]
base_row = ["2026-10-21", "POS transaction", 100, 0, 250, "R1"]
sheet["rows"] = [[x for x in base_header if x != "Balance"],
                 ["2026-10-21", "POS transaction", 100, 0, "R1"]]
try:
    env["_read_rows"]("/private/files/statement.xlsx")
except ValueError as exc:
    assert "Missing required Balance column" in str(exc), str(exc)
else:
    raise AssertionError("Missing Balance column was accepted")

sheet["rows"] = [base_header, ["2026-10-21", "POS transaction", 100, 0, None, "R1"]]
try:
    env["_read_rows"]("/private/files/statement.xlsx")
except ValueError as exc:
    assert "Excel row 2" in str(exc), str(exc)
else:
    raise AssertionError("Blank running balance was accepted")

sheet["rows"] = [base_header, ["2026-10-21", "POS transaction", 100, 0, 0, "R1"]]
assert len(env["_read_rows"]("/private/files/statement.xlsx")) == 1
sheet["rows"] = [base_header, base_row]
assert len(env["_read_rows"]("/private/files/statement.xlsx")) == 1

prior = AttrDict(
    name="OLD1", bank_account="SNB", processing_date="2026-10-21",
    reference_number="R1", debit=100, credit=0, balance=100,
)
candidate = dict(
    processing_date="2026-10-21", reference_number="R1",
    debit=100, credit=0, balance=250,
)
fake.prior = [prior]
assert env["_secondary_financial_identity"](candidate) == env["_secondary_financial_identity"](prior)
assert env["_financial_identity"](candidate) != env["_financial_identity"](prior)
assert env["_secondary_financial_identity"]({**candidate, "reference_number": ""}) is None
strong, secondary = env["_prior_financial_duplicates"](
    SimpleNamespace(bank_account="SNB"), [candidate]
)
assert not strong.get(env["_financial_identity"](candidate))
assert secondary[env["_secondary_financial_identity"](candidate)][0].name == "OLD1"
assert len(fake.calls) <= 2, "Indexed lookup must not scan once per row"

# Run the production analyzer with controlled normalized rows.
def normalize(_doc, row_number, raw, header_map):
    return {
        "processing_date": raw[0], "reference_number": raw[5],
        "debit": raw[2], "credit": raw[3], "balance": raw[4],
        "source_key": f"NEW-{row_number}", "source_row_no": row_number,
        "is_pos_statement_line": 1,
    }

env["_normalize_row"] = normalize
extracted("_analyze", env=env)
doc = SimpleNamespace(bank_account="SNB", import_file="/statement.xlsx")
summary, rows, errors = env["_analyze"](doc)
assert summary["new_records"] == 1
assert summary["total_rows"] == 1
assert summary["review_warning_records"] == 1
assert summary["error_records"] == 0
assert errors[0]["category"] == "Review Warning"

sheet["rows"] = [base_header, ["2026-10-21", "POS transaction", 100, 0, 100, "R1"]]
summary, rows, errors = env["_analyze"](doc)
assert summary["review_warning_records"] == 0
assert any(e["category"] == "Potential Duplicate" for e in errors), errors
assert summary["error_records"] == 1

sheet["rows"] = [base_header, base_row,
                 ["2026-10-21", "POS transaction", 100, 0, 300, "R1"]]
fake.prior = []
summary, rows, errors = env["_analyze"](doc)
assert summary["review_warning_records"] == 1
assert summary["new_records"] == 2
assert summary["total_rows"] == 2

# Warning acknowledgement must be checked by the server, not just the UI.
class FakeDoc:
    name = "MBS-IMP-TEST"
    status = "Draft"
    import_file = "/statement.xlsx"
    def check_permission(self, operation):
        assert operation == "write"


fake.doc = FakeDoc()
fake.enqueued.clear()
env["_analyze"] = lambda _: ({"review_warning_records": 1}, [], [{"category": "Review Warning"}])
env["_save_summary"] = lambda *args: None
env["_file_digest"] = lambda _: "SOURCE-DIGEST"
extracted("start_import", env=env)
try:
    env["start_import"]("MBS-IMP-TEST", acknowledge_possible_duplicates=0)
except ValueError as exc:
    assert "explicit confirmation" in str(exc)
else:
    raise AssertionError("Unreviewed possible duplicates were accepted")

queued = env["start_import"]("MBS-IMP-TEST", acknowledge_possible_duplicates=1)
assert queued["queued"] == 1
assert len(fake.enqueued) == 1
assert fake.enqueued[0]["acknowledge_possible_duplicates"] == 1
assert fake.enqueued[0]["expected_file_digest"] == "SOURCE-DIGEST"

fields = {x["fieldname"] for x in SCHEMA["fields"]}
assert {"review_warning_records", "duplicate_reviewed_by", "duplicate_reviewed_on"} <= fields
assert "acknowledge_possible_duplicates" in WRAPPER
assert "acknowledge_possible_duplicates: acknowledged ? 1 : 0" in UI
assert "review_warning_records" in UI
assert "_file_digest(doc.import_file) != expected_file_digest" in SOURCE
assert SOURCE.count('row.get("category") == "Potential Duplicate"') == 2
print("SNB statement header, blank balance, candidate warnings, review and audit safeguards passed.")
