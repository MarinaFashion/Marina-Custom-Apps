"""Test real manual-link validation and cross-profile reconciliation scoping.

Runs without a Frappe bench. These tests compile the actual service/engine
functions, use fake read-only source transactions, and check the UI evidence.
No real bank, statement, settlement, or accounting data is modified.
"""
import ast
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "manual_alhamrani_link_service.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "reconciliation_engine.py").read_text(encoding="utf-8")
JS = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(
    encoding="utf-8"
)


class Bag(dict):
    __getattr__ = dict.get


def fn(source, name, ns):
    node = next(
        x for x in ast.parse(source).body
        if isinstance(x, ast.FunctionDef) and x.name == name
    )
    node.decorator_list = []
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), name, "exec"),
        ns,
    )
    return ns[name]


def fail(message, *args):
    raise ValueError(str(message))


class Db:
    def exists(self, dt, name):
        if dt == "Manual Alhamrani POS Link":
            return False
        return True

    def get_single_value(self, *args):
        return 60


class Frappe:
    ValidationError = ValueError
    db = Db()
    throw = staticmethod(fail)

    @staticmethod
    def get_all(doctype, filters=None, fields=None, limit_page_length=None):
        assert doctype == "Bank POS Transaction"
        assert filters == {
            "rrn": "123456789012",
            "transaction_date": "2026-10-25",
            "transaction_status": ["in", ["Approved", "APPROVED", "approved"]],
        }, filters
        return [
            Bag(
                name="BANK-A", rrn="123456789012",
                transaction_date="2026-10-25", pos_profile="POS-A",
                transaction_amount=200.00, transaction_type="PURCHASE",
                transaction_status="Approved",
                terminal_id="TERM-A", transaction_time="14:25:00",
            )
        ]

    @staticmethod
    def get_doc(*args):
        return SimpleNamespace(as_dict=lambda: Bag(response_meaning="Approved"))


def cstr(x):
    return "" if x is None else str(x)


def flt(x, places=2):
    return round(float(x or 0), places)


bank = Bag(
    name="BANK-A", rrn="123456789012", transaction_date="2026-10-25",
    pos_profile="POS-A", transaction_amount=200.00, transaction_type="PURCHASE",
    transaction_status="Approved",
)
alh = Bag(
    name="ALH-B", rrn="123456789012", transaction_date="2026-10-25",
    pos_profile="POS-B", amount=200.00, transaction_type="PURCHASE",
    status="Approved", terminal_id="TERM-B", transaction_time="14:26:00",
    comparison_transaction_time=None, source_pos_profile="POS-B",
)


class Adapter:
    fields = {}
    def is_approved(self, raw):
        return True

    def normalized_row(self, raw):
        return Bag(alh)


ns = {
    "frappe": Frappe,
    "_": lambda x: x,
    "cstr": cstr,
    "flt": flt,
    "getdate": lambda x: date.fromisoformat(str(x)),
    "re": re,
    "_require_approver": lambda: None,
    "ALHAMRANI_DOCTYPE": "Alhamrani Transaction",
    "AlhamraniAdapter": Adapter,
    "resolve_pos_profile": lambda *args: None,
    "LINK": "Manual Alhamrani POS Link",
}

validate = fn(SERVICE, "validate_manual_pair", ns)
find_candidates = fn(SERVICE, "find_manual_link_candidates", ns)

# Cross-profile matching is allowed if all actual payment evidence agrees.
validate(bank, alh)
result = find_candidates("ALH-B")
assert len(result) == 1
assert result[0]["pos_profile"] == "POS-A"
assert result[0]["alhamrani"]["pos_profile"] == "POS-B"
assert result[0]["amount"] == result[0]["alhamrani"]["amount"] == 200.00

# Missing profiles must not turn otherwise evidenced matches into failures.
validate(Bag(bank, pos_profile=None), Bag(alh, pos_profile=None))

# These are still hard failures.
for wrong_bank, wrong_alh, expected in [
    (Bag(bank, rrn="123456789013"), alh, "RRN"),
    (Bag(bank, transaction_amount=205), alh, "amounts"),
    (Bag(bank, transaction_date="2026-10-24"), alh, "dates"),
    (Bag(bank, transaction_type="REFUND"), alh, "types"),
    (Bag(bank, transaction_status="Declined"), alh, "approved"),
    (bank, Bag(alh, status="Declined"), "approved"),
]:
    try:
        validate(wrong_bank, wrong_alh)
        raise AssertionError("Invalid payment evidence was accepted: " + expected)
    except ValueError as exc:
        assert expected.lower() in str(exc).lower(), (expected, str(exc))

# Execute the production Alhamrani source selection with a scoped bank in
# POS-A and a manually linked Alhamrani transaction in POS-B.
alh_rows = [
    Bag(
        name="ALH-B", transaction_date="2026-10-25", pos_profile="POS-B",
        source_pos_profile="POS-B", terminal_id="TERM-B", card_type="VC",
    ),
    Bag(
        name="ALH-UNLINKED", transaction_date="2026-10-25", pos_profile="POS-B",
        source_pos_profile="POS-B", terminal_id="TERM-U", card_type="VC",
    ),
    Bag(
        name="ALH-A", transaction_date="2026-10-25", pos_profile="POS-A",
        source_pos_profile="POS-A", terminal_id="TERM-A", card_type="P1",
    ),
]


class SourceAdapter:
    def get_rows(self, date_from, date_to):
        return alh_rows

    def is_approved(self, raw):
        return True

    def normalized_row(self, raw):
        return Bag(raw)


eng_ns = {
    "AlhamraniAdapter": SourceAdapter,
    "getdate": lambda x: date.fromisoformat(str(x)),
    "resolve_pos_profile": lambda *args: None,
}
read_sources = fn(ENGINE, "_alhamrani_rows", eng_ns)
mapper = SimpleNamespace(
    resolve=lambda x: x,
    alhamrani=lambda x: x,
)
run = Bag(from_date="2026-10-25", to_date="2026-10-25", pos_profile="POS-A", card_type="P1")
bank_rows = [Bag(name="BANK-A", pos_profile="POS-A")]

without_link = read_sources(run, mapper, bank_rows, {})
assert {x.name for x in without_link} == {"ALH-A"}
with_link = read_sources(run, mapper, bank_rows, {"BANK-A": "ALH-B"})
assert {x.name for x in with_link} == {"ALH-A", "ALH-B"}

# A manual link on an unrelated bank must not include that source in the run.
unrelated = read_sources(run, mapper, bank_rows, {"BANK-OUTSIDE": "ALH-B"})
assert {x.name for x in unrelated} == {"ALH-A"}

# Reconciliation uses one approved link snapshot for loading and matching.
assert "manual_links = active_manual_links()" in ENGINE
assert "bank_rows=bank_rows, manual_links=manual_links" in ENGINE
assert "time_tolerance_seconds=time_tolerance, manual_links=manual_links" in ENGINE
assert 'if manual_links is None:' in ENGINE

# The end-user sees each profile separately, even when they differ.
assert 'source.pos_profile, candidate.pos_profile' in JS
assert 'Review only' in JS
assert "Both POS Profiles are shown for your confirmation" in JS
assert "POS Profiles differ (Alhamrani:" in JS
assert "I reviewed both POS Profiles, Amount, Date and Time" in JS
assert "date and POS Profile" not in JS
print("Cross-profile candidate selection, strict evidence, scoped rerun, and UI safeguards passed")
