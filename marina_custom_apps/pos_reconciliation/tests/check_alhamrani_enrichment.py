"""Exercise production enrichment/rollback functions using a dependency-free Frappe stub.

Runs on GitHub Actions without a Frappe bench. It does not touch any site.
"""
import ast
import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "manual_alhamrani_enrichment.py").read_text()
SERVICE = (ROOT / "manual_alhamrani_link_service.py").read_text()
DELETE_HOOK = (ROOT / "doctype/manual_alhamrani_pos_link/manual_alhamrani_pos_link.py").read_text()


def load_function(text, name, ns):
    matches = [
        x for x in ast.parse(text).body
        if isinstance(x, ast.FunctionDef) and x.name == name
    ]
    assert len(matches) == 1, name
    code = compile(ast.Module(body=matches, type_ignores=[]), name, "exec")
    exec(code, ns)
    return ns[name]


def as_string(value):
    return "" if value is None else str(value)


class Dict(dict):
    def __getattr__(self, name):
        return self[name]


class Db:
    def __init__(self, source):
        self.source = source
        self.writes = []

    def sql(self, query, args):
        assert "FOR UPDATE" in query
        assert args == ("AUP-1",)

    def set_value(self, doctype, name, values, update_modified):
        assert doctype == "Alhamrani Transaction"
        assert name == "AUP-1"
        assert isinstance(values, dict)
        self.writes.append(values)
        self.source.update(values)

    def get_value(self, doctype, name, names, as_dict):
        assert doctype == "Alhamrani Transaction"
        assert name == "AUP-1"
        return {key: self.source.get(key) for key in names}


class Link:
    def __init__(self):
        self.bank_pos_transaction = "BPT-1"
        self.alhamrani_transaction = "AUP-1"
        self.fields = {}

    def db_set(self, values, value=None, update_modified=True):
        if isinstance(values, dict):
            self.fields.update(values)
        else:
            self.fields[values] = value

    def get(self, name):
        return self.fields.get(name)


class Meta:
    def __init__(self, source):
        self.source = source

    def has_field(self, name):
        return name in self.source


def make_system(source, site="marinademo.frappe.cloud"):
    db = Db(source)
    frappe = SimpleNamespace(
        local=SimpleNamespace(site=site),
        db=db,
        session=SimpleNamespace(user="test@example.org"),
        get_doc=lambda doctype, name: SimpleNamespace(as_dict=lambda: dict(db.source)),
        get_meta=lambda doctype: Meta(db.source),
        throw=lambda msg: (_ for _ in ()).throw(ValueError(msg)),
    )
    ns = dict(
        frappe=frappe,
        cstr=as_string,
        now_datetime=lambda: datetime(2026, 10, 25, 20, 0),
        json=json,
        re=re,
        _=lambda msg: msg,
        ALHAMRANI_DOCTYPE="Alhamrani Transaction",
        is_manual_slip_confirmation=lambda value: value == "Confirmed manually from terminal slip",
        resolve_pos_profile=lambda terminal_id, date: "POS50",
        FIELD_MAPPING=(
            ("card_type", ("card_type",)),
            ("masked_card_number", ("masked_pan", "masked_card_number")),
            ("terminal_id", ("tid", "terminal_id", "device_terminal_id")),
            ("auth_code", ("auth_code", "authorization_code")),
            ("transaction_time", ("transaction_time",)),
        ),
    )
    for name in ("_is_blank", "_safe_masked_pan", "_eligible_changes",
                 "apply_enrichment", "rollback_enrichment"):
        load_function(SOURCE, name, ns)
    bank = Dict(
        name="BPT-1", card_type="P1", masked_card_number="******1234",
        terminal_id="TID-42", auth_code="123456",
        transaction_time="14:20:45", transaction_date="2026-10-25",
    )
    return ns, frappe, bank, Link()


source = dict(
    name="AUP-1", pos_profile="POS50",
    response_meaning="Confirmed manually from terminal slip",
    card_type=None, masked_pan="", tid="", auth_code=None, transaction_time="",
    amount="379.00", rrn="123456789012", request_json="ORIGINAL REQUEST",
    response_json="ORIGINAL RESPONSE",
)
ns, frappe, bank, link = make_system(source)
result = ns["apply_enrichment"](link, bank)
assert result["status"] == "Applied", result
assert set(result["fields"]) == {"card_type", "masked_pan", "tid", "auth_code", "transaction_time"}
assert frappe.db.source["card_type"] == "P1"
assert frappe.db.source["tid"] == "TID-42"
assert frappe.db.source["response_json"] == "ORIGINAL RESPONSE"
assert frappe.db.source["request_json"] == "ORIGINAL REQUEST"
assert frappe.db.source["amount"] == "379.00"
assert frappe.db.source["response_meaning"] == "Confirmed manually from terminal slip"
audit = json.loads(link.get("enrichment_details"))
assert len(audit["changes"]) == 5
ns["rollback_enrichment"](link)
assert frappe.db.source["card_type"] is None
assert frappe.db.source["tid"] == ""
assert frappe.db.source["response_meaning"] == "Confirmed manually from terminal slip"

# Never overwrite nonempty source values or import unmasked bank card numbers.
ns, frappe, bank, link = make_system(dict(source, card_type="VC", masked_pan=""))
bank["masked_card_number"] = "4111111111111111"
result = ns["apply_enrichment"](link, bank)
assert "card_type" not in result["fields"]
assert "masked_pan" not in result["fields"]
assert frappe.db.source["card_type"] == "VC"

# A changed enriched value must block unlinking instead of overwriting it.
ns, frappe, bank, link = make_system(dict(source))
ns["apply_enrichment"](link, bank)
frappe.db.source["auth_code"] = "OVERRIDDEN"
try:
    ns["rollback_enrichment"](link)
    raise AssertionError("Unsafe unlink unexpectedly succeeded")
except ValueError as exc:
    assert "changed after enrichment" in str(exc)
assert frappe.db.source["auth_code"] == "OVERRIDDEN"

# Regular electronic terminal responses are never rewritten by this feature.
ns, frappe, bank, link = make_system(dict(source, response_meaning="Approved"))
result = ns["apply_enrichment"](link, bank)
assert result["status"] == "Not Applicable"
assert frappe.db.writes == []

# Demo-only, while preserving approvals on other sites.
ns, frappe, bank, link = make_system(dict(source), site="marina.frappe.cloud")
result = ns["apply_enrichment"](link, bank)
assert result["status"] == "Disabled"
assert frappe.db.writes == []

assert "enrichment = apply_enrichment(doc, bank)" in SERVICE
assert "rollback_enrichment(self)" in DELETE_HOOK
assert DELETE_HOOK.index("_assert_no_financial_dependencies(") < DELETE_HOOK.index("rollback_enrichment(self)")
assert "frappe.db.commit(" not in SERVICE
assert "frappe.db.commit(" not in SOURCE
assert "frappe.db.delete(" not in SOURCE
print("Alhamrani enrichment, masked PAN, and safe rollback checks passed")
