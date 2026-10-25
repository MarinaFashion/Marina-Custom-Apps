"""Exercise real controlled unlink, without an ERPNext site.

A request-scope flag gates direct Delete; the link is removed ONLY after
financial dependency preflight and reversible enrichment cleanup. No Revoked
record or separate unlink record is created.
"""
import ast
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "manual_alhamrani_link_service.py").read_text()
HOOK = (ROOT / "doctype/manual_alhamrani_pos_link/manual_alhamrani_pos_link.py").read_text()


class Bag(dict):
    def __getattr__(self, key):
        return self.get(key)


class Database:
    def __init__(self):
        self.reset()

    def reset(self):
        self.links = {
            "LINK-1": Bag(
                name="LINK-1", status="Approved",
                bank_pos_transaction="BPT-1",
                alhamrani_transaction="AUP-1",
                enrichment_details='{"changes":[{"source_field":"pan"}]}',
            )
        }
        self.settlement = Bag(bank_pos_transaction="BPT-1", settled=1,
                              settlement_number="SET-1", journal_entry=None)
        self.alhamrani = Bag(pan="******1234", tid="TID-1")
        self.events = []
        self.error = None

    def sql(self, query, args):
        assert "FOR UPDATE" in query
        assert args == ("LINK-1",)
        self.events.append("lock")

    def delete(self, doctype, name):
        self.events.append("delete")
        del self.links[name]


db = Database()
class Flags(dict):
    __getattr__ = dict.get
frappe = SimpleNamespace(
    local=SimpleNamespace(site="marinademo.frappe.cloud"),
    flags=Flags(),
    session=SimpleNamespace(user="finance@example.org"),
    db=db,
    get_doc=lambda dt, name: db.links[name],
    get_roles=lambda: ["Accounts Manager"],
    PermissionError=PermissionError,
    throw=lambda message, *args: (_ for _ in ()).throw(ValueError(str(message))),
)
ns = {
    "frappe": frappe, "_": lambda s: s,
    "cstr": lambda value: "" if value is None else str(value),
    "LINK": "Manual Alhamrani POS Link",
}


def protected(bank, alh):
    assert bank == "BPT-1" and alh == "AUP-1"
    assert db.events == ["lock"]
    db.events.append("preflight")
    if db.error == "posting":
        raise ValueError("commission/VAT posting prevents unlink")
    if db.error == "settlement":
        raise ValueError("bank settlement references unsafe")
    if db.error == "closed":
        raise ValueError("Closed finance period")


def restore(doc):
    assert db.events == ["lock", "preflight"]
    db.events.append("restore")
    if db.error == "restore":
        raise ValueError("Alhamrani PAN changed after enrichment")
    db.alhamrani["pan"] = None
    db.alhamrani["tid"] = None


def require_approver():
    if db.error == "role":
        raise ValueError("Accounts Manager required")


ns.update({
    "_require_approver": require_approver,
    "_assert_no_financial_dependencies": protected,
    "rollback_enrichment": restore,
})


def install_function(source, name, class_name=None):
    tree = ast.parse(source)
    scope = tree.body
    if class_name:
        scope = next(n.body for n in tree.body
                     if isinstance(n, ast.ClassDef) and n.name == class_name)
    func = next(n for n in scope if isinstance(n, ast.FunctionDef) and n.name == name)
    func.decorator_list = []
    func.body = [
        ast.Pass() if isinstance(x, ast.ImportFrom) else x
        for x in func.body
    ]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])),
                 name, "exec"), ns)
    return ns[name]


guard = install_function(HOOK, "on_trash", "ManualAlhamraniPOSLink")


def perform_delete(doctype, name, ignore_permissions=False):
    assert ignore_permissions is True
    assert doctype == "Manual Alhamrani POS Link"
    assert name == "LINK-1"
    assert db.events == ["lock", "preflight", "restore"]
    guard(Bag(name="LINK-1"))
    db.delete(doctype, name)


frappe.delete_doc = perform_delete
unlink = install_function(SERVICE, "unlink_manual_link")

# Direct Delete, even by a Finance Manager, is always rejected.
try:
    guard(Bag(name="LINK-1"))
    raise AssertionError("Direct Delete was permitted")
except ValueError as exc:
    assert "Direct deletion is not allowed" in str(exc)
assert db.links["LINK-1"]["status"] == "Approved"

def blocked(error, expected):
    db.reset()
    db.error = error
    try:
        unlink("LINK-1")
        raise AssertionError("Unsafe unlink was permitted: " + error)
    except ValueError as exc:
        assert expected in str(exc), str(exc)
    assert "delete" not in db.events
    assert db.links["LINK-1"]["status"] == "Approved"
    assert frappe.flags == {}, "Scoped Delete permission escaped a failing request"


blocked("role", "Accounts Manager")
blocked("posting", "commission/VAT")
blocked("settlement", "bank settlement")
blocked("closed", "Closed")
blocked("restore", "changed after enrichment")

db.reset()
frappe.local.site = "marina.frappe.cloud"
try:
    unlink("LINK-1")
    raise AssertionError("Live unlink should be disabled")
except ValueError as exc:
    assert "Demo only" in str(exc)
assert db.events == []
frappe.local.site = "marinademo.frappe.cloud"

# A permitted, already-settled transaction with no accounting postings can
# be safely unlinked; settlement/statement records remain unchanged.
db.reset()
result = unlink("LINK-1")
assert result["unlinked"] is True
assert result["requires_reconciliation"] is True
assert result["bank_pos_transaction"] == "BPT-1"
assert result["alhamrani_transaction"] == "AUP-1"
assert db.events == ["lock", "preflight", "restore", "delete"]
assert db.links == {}
assert db.settlement.settled == 1 and db.settlement.settlement_number == "SET-1"
assert db.alhamrani.pan is None and db.alhamrani.tid is None
assert frappe.flags == {}, "Unlink privilege must not survive its own request"

# A failed second unlink cannot remove any other payment.
try:
    unlink("LINK-1")
    raise AssertionError("Duplicate unlink unexpectedly succeeded")
except KeyError:
    pass

# Direct deletion cannot be granted for a different record by the flag.
frappe.flags["_authorized_manual_alhamrani_unlink"] = "LINK-2"
try:
    guard(Bag(name="LINK-1"))
    raise AssertionError("Wrong flag could delete another Manual Link")
except ValueError as exc:
    assert "Direct deletion is not allowed" in str(exc)
frappe.flags.pop("_authorized_manual_alhamrani_unlink")

assert "frappe.db.commit(" not in SERVICE
assert "frappe.db.delete(" not in SERVICE
assert "frappe.delete_doc(LINK, link_name, ignore_permissions=True)" in SERVICE
assert "original_bank_pos_transaction" not in SERVICE
assert '"status": "Revoked"' not in SERVICE
print("Controlled unlink, protected accounting, and direct Delete prevention passed")
