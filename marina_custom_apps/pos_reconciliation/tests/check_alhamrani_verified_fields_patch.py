"""Dependency-free CI guard for Demo migration of Bank Verified Alhamrani fields."""
import ast
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
path = root / "patches/v0_53_25/add_alhamrani_bank_verified_fields.py"
source = path.read_text()
patches = (root / "patches.txt").read_text()
enrichment = (root / "pos_reconciliation/manual_alhamrani_enrichment.py").read_text()

assert "marina_custom_apps.patches.v0_53_25.add_alhamrani_bank_verified_fields" in patches
assert '"custom_bank_masked_pan"' in enrichment
assert '"custom_bank_transaction_time"' in enrichment

calls = []


def create_custom_fields(mapping, update=False):
    calls.append((mapping, update))


class Database:
    @staticmethod
    def exists(doctype, value):
        return doctype == "DocType" and value == "Alhamrani Transaction"


def make_frappe(site, has_response_meaning=True):
    return SimpleNamespace(
        local=SimpleNamespace(site=site),
        db=Database(),
        get_meta=lambda doctype: SimpleNamespace(
            has_field=lambda field: field == "response_meaning" and has_response_meaning
        ),
        clear_cache=lambda **kwargs: calls.append(("clear_cache", kwargs)),
        throw=lambda message: (_ for _ in ()).throw(RuntimeError(message)),
    )


tree = ast.parse(source)
method = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "execute")
ns = {
    "frappe": make_frappe("marina.frappe.cloud"),
    "create_custom_fields": create_custom_fields,
}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), ns)
execute = ns["execute"]
execute()
assert calls == [], "Live must not receive the Demo-only Custom Fields"

ns["frappe"] = make_frappe("marinademo.frappe.cloud")
execute()
assert len(calls) == 2
mapping, update = calls[0]
assert update
fields = {x["fieldname"]: x for x in mapping["Alhamrani Transaction"]}
assert set(fields) == {
    "custom_bank_verified_section", "custom_bank_masked_pan",
    "custom_bank_transaction_time"
}
assert fields["custom_bank_masked_pan"]["fieldtype"] == "Data"
assert fields["custom_bank_masked_pan"]["read_only"] == 1
assert fields["custom_bank_transaction_time"]["fieldtype"] == "Time"
assert fields["custom_bank_transaction_time"]["read_only"] == 1
assert fields["custom_bank_verified_section"]["insert_after"] == "response_meaning"
assert fields["custom_bank_masked_pan"]["insert_after"] == "custom_bank_verified_section"
assert fields["custom_bank_transaction_time"]["insert_after"] == "custom_bank_masked_pan"
assert all(fields[f]["no_copy"] == 1 for f in (
    "custom_bank_masked_pan", "custom_bank_transaction_time"
))
assert calls[1][0] == "clear_cache"
ns["frappe"] = make_frappe("marinademo.frappe.cloud", False)
try:
    execute()
    raise AssertionError("Migration must block ambiguous manual-slip source schema")
except RuntimeError as e:
    assert "Response Meaning" in str(e)
print("Demo-only custom field migration safety checks passed")
