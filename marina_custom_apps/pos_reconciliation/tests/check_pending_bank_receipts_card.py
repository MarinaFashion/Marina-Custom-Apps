"""Dependency-free check for the real Frappe-compatible Pending Receipts KPI.

Exercises the production _filtered_summary() and rejects SQL CASE/COALESCE
expressions, which Frappe v15 does not permit in get_all field selectors.
Tests filtering, gross source selection, 8-card presentation and performance.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "review_service.py").read_text(encoding="utf-8")
UI = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(
    encoding="utf-8"
)
source = next(
    node for node in ast.parse(SERVICE).body
    if isinstance(node, ast.FunctionDef) and node.name == "_filtered_summary"
)
assert "sum(CASE" not in SERVICE
assert "COALESCE(" not in SERVICE
assert '"match_status",' in SERVICE
assert '"sum(bank_amount) as bank_gross"' in SERVICE
assert '"sum(alhamrani_amount) as alhamrani_gross"' in SERVICE
assert 'group_by="match_status"' in SERVICE
assert '"pending_bank_receipts": pending_bank_receipts' in SERVICE

rows = [
    {"status": "Matching Not Settled", "profile": "POS01", "bank": 100.00, "alhamrani": 100.00},
    {"status": "Alhamrani Only", "profile": "POS01", "bank": 0.00, "alhamrani": 250.00},
    {"status": "Fully Matching", "profile": "POS01", "bank": 400.00, "alhamrani": 400.00},
    {"status": "Bank Only - Not Settled", "profile": "POS01", "bank": 500.00, "alhamrani": 0.00},
    {"status": "Bank Only - Settled", "profile": "POS01", "bank": 300.00, "alhamrani": 0.00},
    {"status": "Discrepancy", "profile": "POS01", "bank": 600.00, "alhamrani": 550.00},
    {"status": "Matching Not Settled", "profile": "POS02", "bank": 60.00, "alhamrani": 60.00},
    {"status": "Alhamrani Only", "profile": "POS02", "bank": 0.00, "alhamrani": 70.00},
]
calls = []


def filtered_rows(filters):
    result = []
    for row in rows:
        if filters.get("pos_profile") and row["profile"] != filters["pos_profile"]:
            continue
        requested = filters.get("match_status")
        if requested:
            allowed = requested[1] if isinstance(requested, list) else [requested]
            if row["status"] not in allowed:
                continue
        result.append(row)
    return result


def fake_get_all(
    doctype, filters=None, or_filters=None, fields=None, group_by=None, limit_page_length=None
):
    assert doctype == "POS Reconciliation Record"
    assert filters is not None
    assert fields
    assert all("CASE" not in col and "COALESCE" not in col for col in fields)
    assert len(calls) < 40, "Unexpected per-transaction SQL queries"
    calls.append((filters, or_filters, fields, group_by, limit_page_length))
    included = filtered_rows(filters)

    if group_by is None:
        assert limit_page_length == 1
        assert len(fields) == 6
        return [{
            "transaction_count": len(included),
            "gross_amount": sum(row["bank"] for row in included),
            "marina_amount": sum(row["alhamrani"] for row in included),
            "commission": 0,
            "vat": 0,
            "bank_settlement_amount": 0,
        }]

    assert group_by == "match_status"
    assert limit_page_length == 0
    assert fields == [
        "match_status",
        "sum(bank_amount) as bank_gross",
        "sum(alhamrani_amount) as alhamrani_gross",
    ]
    grouped = {}
    for row in included:
        values = grouped.setdefault(
            row["status"], {"match_status": row["status"], "bank_gross": 0, "alhamrani_gross": 0}
        )
        values["bank_gross"] += row["bank"]
        values["alhamrani_gross"] += row["alhamrani"]
    return list(grouped.values())


def fake_flt(value, digits=2):
    return round(float(value or 0), digits)


namespace = {
    "frappe": SimpleNamespace(get_all=fake_get_all, _dict=lambda: {}),
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
    first = len(calls)
    search = {"terminal_id": ["like", "%ABC%"]}
    result = summary(filters, or_filters=search)
    assert result["pending_bank_receipts"] == expected, (filters, result)
    assert len(calls) == first + 2, "One original summary + one GROUP BY query per view"
    for query in calls[first:]:
        assert query[0] is filters, "Selected status/date/profile filters must be identical"
        assert query[1] is search, "Search conditions must be forwarded to both aggregates"


check({"run": "POS Reconciliation Run"}, 980.00)
check({"run": "POS Reconciliation Run", "pos_profile": "POS01"}, 850.00)
check({"run": "POS Reconciliation Run", "pos_profile": "POS02"}, 130.00)
check({"run": "POS Reconciliation Run", "match_status": "Matching Not Settled"}, 160.00)
check({"run": "POS Reconciliation Run", "match_status": "Alhamrani Only"}, 320.00)
check({"run": "POS Reconciliation Run", "match_status": "Fully Matching"}, 0.00)
check({"run": "POS Reconciliation Run", "match_status": "Bank Only - Not Settled"}, 500.00)
check({"run": "POS Reconciliation Run", "match_status": "Bank Only - Settled"}, 0.00)
check({"run": "POS Reconciliation Run", "match_status": "Discrepancy"}, 0.00)
check({"run": "POS Reconciliation Run", "match_status": ["in", ["Matching Not Settled", "Alhamrani Only"]]}, 480.00)
check({"run": "POS Reconciliation Run", "match_status": "__NONE__"}, 0.00)

section = UI.split('__("Financial Totals")', 1)[1].split('__("Finance & Accounting Status")', 1)[0]
assert section.count("</b><span>") == 8
assert section.count('__("Pending Bank Receipts")') == 1
assert "pos_recon_money(summary.pending_bank_receipts)" in section
assert '__("VAT %")' not in section
assert '__("Commission %")' in section
assert "not proof of an outstanding bank deposit" in section.lower()
assert ".pos-recon-summary-financial" in UI
print("Frappe-safe grouped summary, filters, three sources and eight-card layout passed.")
