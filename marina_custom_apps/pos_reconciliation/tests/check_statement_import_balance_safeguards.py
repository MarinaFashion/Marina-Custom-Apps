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
    "IMPORT_DOCTYPE": "Marina Bank Statement Import",
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
assert summary["review_warning_records"] == 2
assert summary["new_records"] == 2
assert summary["total_rows"] == 2

# Review identities bind to bank, XLSX fingerprint, DB duplicate evidence and rows.
class FakeDoc:
    name = "MBS-IMP-TEST"
    company = "Marina"
    bank_account = "SNB"
    status = "Draft"
    import_file = "/statement.xlsx"
    inserted_records = 0
    def check_permission(self, operation):
        assert operation == "write"
    def db_set(self, field, value, **kwargs):
        setattr(self, field, value)
    def add_comment(self, kind, text):
        assert kind == "Info"
        audit_comments.append(text)


fake.doc = FakeDoc()
fake.enqueued.clear()
env["_file_digest"] = lambda _: "SOURCE-DIGEST"
env["_save_summary"] = lambda *args: None
env["json"] = json
env["hashlib"] = __import__("hashlib")
extracted("_review_plan", "_validated_review_decisions", "_reviewed_rows", "start_import",
          "get_duplicate_review", "process_import", env=env)
summary, rows, errors = env["_analyze"](fake.doc)
token, review, blocked = env["_review_plan"](fake.doc, rows, errors)
assert len(review) == 2, "Both in-file ambiguous rows must be reviewable"
assert not blocked
assert [x["row_number"] for x in review] == [2, 3]
decisions = {"2": "skip", "3": "import"}
eligible, reviewed, excluded_exact, approved, skipped = env["_reviewed_rows"](
    fake.doc, rows, errors, decisions, token,
)
assert [x["source_row_no"] for x in eligible] == [3], eligible
assert approved == {3} and skipped == {2}
assert len(reviewed) == 2 and not excluded_exact
for invalid in (
    {}, {"2": "import"}, {"2": "skip", "3": "wrong"},
    {"2": "skip", "3": "skip", "4": "import"},
):
    try:
        env["_validated_review_decisions"](review, blocked, invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Accepted unsafe row review: {invalid}")
try:
    env["_reviewed_rows"](fake.doc, rows, errors, decisions, "outdated-token")
except ValueError as exc:
    assert "changed since review" in str(exc)
else:
    raise AssertionError("Outdated review was accepted")

try:
    env["start_import"]("MBS-IMP-TEST", review_decisions={}, expected_review_token=token)
except ValueError:
    pass
else:
    raise AssertionError("Server accepted unresolved duplicate candidates")

queued = env["start_import"](
    "MBS-IMP-TEST", review_decisions=json.dumps(decisions), expected_review_token=token
)
assert queued["queued"] == 1
assert queued["review_import"] == 1 and queued["review_skip"] == 1
assert queued["ready_to_import"] == 1
assert fake.enqueued[-1]["review_decisions"] == json.dumps(decisions)
assert fake.enqueued[-1]["expected_file_digest"] == "SOURCE-DIGEST"

# The long worker independently validates and inserts ONLY approved candidates.
class FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.failures = []
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def set_value(self, *args, **kwargs):
        self.failures.append((args, kwargs))


fake.db = FakeDB()
fake.log_error = lambda *args: None
fake.get_traceback = lambda: "traceback"
audit_comments = []
audit_files = []
captured = []
env["now_datetime"] = lambda: "2026-11-01 10:00:00"
env["save_file"] = lambda filename, content, doctype, name, is_private: (
    audit_files.append((filename, json.loads(content), doctype, name, is_private))
    or SimpleNamespace(file_url="/private/files/audit.json")
)
env["_bulk_insert"] = lambda rows, user: (
    captured.extend((r["source_row_no"], user) for r in rows) or len(rows)
)
fake.doc.status = "Importing"
env["process_import"](
    "MBS-IMP-TEST", requested_by="accounts@example.com",
    review_decisions=json.dumps(decisions),
    expected_review_token=token, expected_file_digest="SOURCE-DIGEST",
)
assert captured == [(3, "accounts@example.com")], captured
assert fake.doc.status == "Importing"  # document status updated through stubbed _save_summary
assert fake.doc.inserted_records == 1
assert fake.db.commits == 1 and fake.db.rollbacks == 0 and not fake.db.failures
assert len(audit_files) == 1 and audit_files[0][-1] == 1
assert audit_files[0][1]["decisions"][0]["action"] == "skip"
assert audit_files[0][1]["decisions"][1]["action"] == "import"
assert audit_comments and "imported: 1, skipped: 1" in audit_comments[0]

# Changed review token must not result in even a partial insert.
captured.clear()
fake.db.commits = 0
fake.db.rollbacks = 0
env["process_import"](
    "MBS-IMP-TEST", requested_by="accounts@example.com",
    review_decisions=json.dumps(decisions),
    expected_review_token="stale", expected_file_digest="SOURCE-DIGEST",
)
assert not captured
assert fake.db.rollbacks == 1
assert fake.db.failures

fields = {x["fieldname"] for x in SCHEMA["fields"]}
assert "errors" in fields  # Existing validation table retained.
assert "duplicate_reviewed_by" not in fields  # No new database columns.
assert "get_statement_duplicate_review" in WRAPPER
assert "review_decisions=review_decisions" in WRAPPER
assert 'action: "skip"' in UI
assert 'marina-review-select-all' in UI
assert 'marina-review-bulk-import' in UI
assert "expected_review_token" in SOURCE
assert "_file_digest(doc.import_file) != expected_file_digest" in SOURCE
assert "doc.add_comment(" in SOURCE
assert 'frappe.db.rollback()' in SOURCE
print("SNB headers, duplicate detection, row choices, bulk-safe worker and private audit passed.")
