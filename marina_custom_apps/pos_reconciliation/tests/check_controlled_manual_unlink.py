"""Test the real Unlink function with mock Frappe, without a running bench.

Only Demo can revoke, original sources stay in the historical link, source
bank accounting/settlement references are never edited, and a reason is
mandatory. Preflight itself is exercised separately by
check_settled_manual_link_unlink.py.
"""
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "manual_alhamrani_link_service.py").read_text()
DOCHOOK = (ROOT / "doctype/manual_alhamrani_pos_link/manual_alhamrani_pos_link.py").read_text()


class Bag(dict):
    def __getattr__(self, key):
        return self.get(key)


class Db:
    def __init__(self):
        self.writes = []
        self.locks = []
        self.link = Bag(
            name="LINK-1", status="Approved", bank_pos_transaction="BPT-1",
            alhamrani_transaction="AUP-1", rrn="123456789012", amount=379.0,
            reason="Approved from original slip", approved_by="approver@example.org",
            approved_on="2026-10-24 09:00:00",
            enrichment_details='{"changes":[{"source_field":"pan"}]}',
        )
        self.source = Bag(pan="******1234", tid="TID-1")
        self.bank = Bag(
            settled=1, accounting_posting=None,
            journal_entry=None, settlement_number="SETTLEMENT-1",
        )
        self.preflight_failure = False
        self.restore_failure = False

    def sql(self, query, args):
        assert query == "SELECT name FROM `tabManual Alhamrani POS Link` WHERE name=%s FOR UPDATE"
        assert args == ("LINK-1",)
        self.locks.append(args)

    def set_value(self, doctype, name, values, update_modified=False):
        assert doctype == "Manual Alhamrani POS Link" and name == "LINK-1"
        assert update_modified is True
        assert self.locks
        self.writes.append(values)
        self.link.update(values)


db = Db()
site = SimpleNamespace(value="marinademo.frappe.cloud")
user = SimpleNamespace(value="manager@example.org")
role = SimpleNamespace(value=True)


def reject(message, *args):
    raise ValueError(str(message))


def validate_access():
    if not role.value:
        raise PermissionError("Only Accounts Manager or System Manager")


def preflight(bank_name, alh_name):
    assert bank_name == "BPT-1" and alh_name == "AUP-1"
    assert db.locks, "Link lock is required"
    if db.preflight_failure:
        raise ValueError("commission/VAT accounting posting detected")


def rollback(link):
    assert link["status"] == "Approved"
    assert not db.writes, "Restore enrichment before revoking a link"
    if db.restore_failure:
        raise ValueError("Pan changed after enrichment")
    db.source["pan"] = None
    db.source["tid"] = None


frappe = SimpleNamespace(
    local=SimpleNamespace(site="marinademo.frappe.cloud"),
    session=SimpleNamespace(user=user.value),
    db=db,
    get_doc=lambda dt, name: db.link if dt == "Manual Alhamrani POS Link" and name == "LINK-1" else None,
    throw=reject,
)
ns = dict(
    frappe=frappe,
    _=lambda x: x,
    cstr=lambda x: "" if x is None else str(x),
    now_datetime=lambda: datetime(2026, 10, 25, 23, 20),
    LINK="Manual Alhamrani POS Link",
    _require_approver=validate_access,
    _assert_no_financial_dependencies=preflight,
    rollback_enrichment=rollback,
)
tree = ast.parse(SERVICE)
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name == "unlink_manual_link")
# Import injection is only for dependency-free testing; execute the function's
# original business instructions and database writes.
node.decorator_list = []
node.body = [
    ast.Pass() if isinstance(x, ast.ImportFrom)
    else x for x in node.body
]
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
             "<real controlled unlink>", "exec"), ns)
unlink = ns["unlink_manual_link"]


def should_reject(reason_text, reason=None):
    try:
        unlink("LINK-1", "Operator correction: wrong payment mapping"
               if reason is None else reason)
        raise AssertionError("Unsafe unlink unexpectedly succeeded")
    except (ValueError, PermissionError) as exc:
        assert reason_text.lower() in str(exc).lower(), str(exc)


should_reject("between 10 and 2000", reason="Too short")
assert not db.writes
frappe.local.site = "marina.frappe.cloud"
should_reject("Demo only")
assert not db.writes
frappe.local.site = "marinademo.frappe.cloud"
role.value = False
should_reject("Accounts Manager")
assert not db.writes
role.value = True
db.preflight_failure = True
should_reject("commission/VAT")
assert not db.writes
db.preflight_failure = False
db.restore_failure = True
should_reject("changed after enrichment")
assert not db.writes
db.restore_failure = False

result = unlink("LINK-1", "Correction after examining terminal slip")
assert result["status"] == "Revoked"
assert result["requires_reconciliation"] is True
assert db.link.status == "Revoked"
assert db.link.bank_pos_transaction is None
assert db.link.alhamrani_transaction is None
assert db.link.original_bank_pos_transaction == "BPT-1"
assert db.link.original_alhamrani_transaction == "AUP-1"
assert db.link.unlink_reason == "Correction after examining terminal slip"
assert db.link.unlinked_by == user.value
assert db.link.unlinked_on == datetime(2026, 10, 25, 23, 20)
assert db.link.approved_by == "approver@example.org"
assert db.link.reason == "Approved from original slip"
assert "pan" in db.link.enrichment_details, "Old enrichment audit must be retained"
assert db.source["pan"] is None
assert db.source["tid"] is None
assert db.bank.settled == 1
assert db.bank.settlement_number == "SETTLEMENT-1"
assert db.bank.accounting_posting is None
assert db.bank.journal_entry is None
assert len(db.writes) == 1
should_reject("already be unlinked")
assert len(db.writes) == 1

assert "frappe.db.delete(" not in SERVICE
assert "frappe.db.commit(" not in SERVICE
assert "frappe.delete_doc(" not in SERVICE

hook_tree = ast.parse(DOCHOOK)
hook_cls = next(n for n in hook_tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ManualAlhamraniPOSLink")
trash = next(n for n in hook_cls.body if isinstance(n, ast.FunctionDef)
             and n.name == "on_trash")
guard_ns = {"frappe": frappe, "_": lambda x: x}
exec(compile(ast.Module(body=[trash], type_ignores=[]),
             "<direct delete guard>", "exec"), guard_ns)
try:
    guard_ns["on_trash"](object())
    raise AssertionError("Direct deletion should never be permitted")
except ValueError as exc:
    assert "cannot be deleted" in str(exc)

print("Controlled audited unlink, direct delete prohibition, and rollback checks passed")
