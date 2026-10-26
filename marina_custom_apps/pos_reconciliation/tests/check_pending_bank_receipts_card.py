"""Dependency-free checks for the pending bank receipts financial card.

This test compiles the ACTUAL summary function and validates its computed
response, filter pass-through, matching/Alhamrani amount-source selection, and
the existing eight-card dashboard layout. No Frappe bench or database needed.
"""
import ast
import re
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "review_service.py").read_text(encoding="utf-8")
UI = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(
    encoding="utf-8"
)
module = ast.parse(SERVICE)
source = next(
    node for node in module.body
    if isinstance(node, ast.FunctionDef) and node.name == "_filtered_summary"
)

# Independently ensure the SQL aggregates with the exact status/source mapping.
assert SERVICE.count("as pending_bank_receipts") == 1
assert '"WHEN match_status IN (\'Matching Not Settled\', \'Bank Only - Not Settled\') "' in SERVICE
assert '"THEN COALESCE(bank_amount, 0) "' in SERVICE
assert 'WHEN match_status = \'Alhamrani Only\' THEN COALESCE(alhamrani_amount, 0)' in SERVICE
assert 'ELSE 0 END) as pending_bank_receipts' in SERVICE
assert 'pending_bank_receipts = flt(total.get("pending_bank_receipts"), 2)' in SERVICE
assert '"pending_bank_receipts": pending_bank_receipts' in SERVICE

rows = [
    {"status": "Matching Not Settled", "profile": "POS01", "bank": 100.00, "alhamrani": 100.00},
    {"status": "Alhamrani Only", "profile": "POS01", "bank": 0.00, "alhamrani": 250.00},
    {"status": "Fully Matching", "profile": "POS01", "bank": 400.00, "alhamrani": 400.00},
    {"status": "Bank Only - Not Settled", "profile": "POS01", "bank": 500.00, "alhamrani": 0.00},
    {"status": "Discrepancy", "profile": "POS01", "bank": 600.00, "alhamrani": 550.00},
    {"status": "Matching Not Settled", "profile": "POS02", "bank": 60.00, "alhamrani": 60.00},
    {"status": "Alhamrani Only", "profile": "POS02", "bank": 0.00, "alhamrani": 70.00},
]
calls = []


def matching_rows(filters):
    filtered = []
    for item in rows:
        if filters.get("pos_profile") and item["profile"] != filters["pos_profile"]:
            continue
        status = filters.get("match_status")
        if status is not None:
            allowed = status[1] if isinstance(status, list) else [status]
            if item["status"] not in allowed:
                continue
        filtered.append(item)
    return filtered


def fake_get_all(doctype, filters=None, or_filters=None, fields=None, limit_page_length=None):
    assert doctype == "POS Reconciliation Record"
    assert limit_page_length == 1
    assert len(calls) < 15
    queries = [column for column in fields if "as pending_bank_receipts" in column]
    assert len(queries) == 1
    expression = queries[0]
    assert "Matching Not Settled" in expression
    assert "Bank Only - Not Settled" in expression
    assert "Alhamrani Only" in expression
    assert "COALESCE(bank_amount, 0)" in expression
    assert "COALESCE(alhamrani_amount, 0)" in expression
    calls.append((filters, or_filters, len(fields)))
    source_rows = matching_rows(filters)
    # This fake calculation follows the expression under test; independent
    # assertions below enforce that matching is counted ONCE and other
    # statuses are explicitly excluded.
    pending = sum(
        row["bank"] if row["status"] in {"Matching Not Settled", "Bank Only - Not Settled"}
        else row["alhamrani"] if row["status"] == "Alhamrani Only"
        else 0 for row in source_rows
    )
    return [{
        "transaction_count": len(source_rows),
        "gross_amount": sum(row["bank"] for row in source_rows),
        "marina_amount": sum(row["alhamrani"] for row in source_rows),
        "commission": 0,
        "vat": 0,
        "bank_settlement_amount": 0,
        "pending_bank_receipts": pending,
    }]


def fake_flt(value, digits=2):
    return round(float(value or 0), digits)


namespace = {
    "frappe": SimpleNamespace(
        get_all=fake_get_all,
        _dict=lambda: {},
    ),
    "RECONCILIATION_RECORD": "POS Reconciliation Record",
    "flt": fake_flt,
    "cint": lambda x: int(x or 0),
    "_group_counts": lambda *args: {},
    "_distinct_count": lambda *args: 0,
    "ACCOUNTING_ELIGIBLE_STATUSES": [],
}
exec(
    compile(ast.Module(body=[source], type_ignores=[]), "production_filtered_summary", "exec"),
    namespace,
)
summary = namespace["_filtered_summary"]

def check(filters, expected):
    opts = {"search": "POS"}  # ensure OR criteria forwarded unchanged
    result = summary(filters, or_filters=opts)
    assert result["pending_bank_receipts"] == expected, (filters, result)
    assert calls[-1][0] is filters and calls[-1][1] is opts
    assert calls[-1][2] == 7, "Keep all financial sums in ONE query"

check({"run": "POS Reconciliation Run"}, 980.00)
check({"run": "POS Reconciliation Run", "pos_profile": "POS01"}, 850.00)
check({"run": "POS Reconciliation Run", "pos_profile": "POS02"}, 130.00)
check({"run": "POS Reconciliation Run", "match_status": "Matching Not Settled"}, 160.00)
check({"run": "POS Reconciliation Run", "match_status": "Alhamrani Only"}, 320.00)
check({"run": "POS Reconciliation Run", "match_status": "Fully Matching"}, 0.00)
check({"run": "POS Reconciliation Run", "match_status": "Bank Only - Not Settled"}, 500.00)
check({"run": "POS Reconciliation Run", "match_status": "Discrepancy"}, 0.00)

# The dashboard financial totals must stay 2x4 on desktop.
section = UI.split('__("Financial Totals")', 1)[1].split('__("Finance & Accounting Status")', 1)[0]
assert section.count("</b><span>") == 8
assert section.count('__("Pending Bank Receipts")') == 1
assert "pos_recon_money(summary.pending_bank_receipts)" in section
assert '__("VAT %")' not in section
assert '__("Commission %")' in section
assert "not proof of an outstanding bank deposit" in section.lower()
assert ".pos-recon-summary-financial" in UI
print("Pending Bank Receipts formula, scoped totals and eight-card layout validated.")
