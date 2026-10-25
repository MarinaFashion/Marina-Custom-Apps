"""Dependency-free checks for the Demo-only bank transaction-time migration."""
import ast
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
source = (root / "patches/v0_53_25/add_bank_verified_transaction_time.py").read_text()
patches = (root / "patches.txt").read_text()
assert "marina_custom_apps.patches.v0_53_25.add_bank_verified_transaction_time" in patches

calls = []


def create_custom_fields(mapping, update=False):
    calls.append((mapping, update))


def fake_frappe(site, exists=True, fields=("response_meaning", "pan")):
    def throw(msg):
        raise ValueError(msg)
    return SimpleNamespace(
        local=SimpleNamespace(site=site),
        db=SimpleNamespace(exists=lambda dt, name: exists),
        get_meta=lambda dt: SimpleNamespace(has_field=lambda f: f in fields),
        throw=throw,
        clear_cache=lambda **kwargs: calls.append(("cache", kwargs)),
    )


function = next(
    n for n in ast.parse(source).body
    if isinstance(n, ast.FunctionDef) and n.name == "execute"
)
ns = {
    "frappe": fake_frappe("marina.frappe.cloud"),
    "create_custom_fields": create_custom_fields,
}
exec(compile(ast.Module(body=[function], type_ignores=[]), "<patch>", "exec"), ns)
execute = ns["execute"]

execute()
assert calls == [], "Migration must have no impact on Live"

ns["frappe"] = fake_frappe("marinademo.frappe.cloud", exists=False)
execute()
assert calls == [], "External Alhamrani integration may be absent"

ns["frappe"] = fake_frappe("marinademo.frappe.cloud", fields=("response_meaning",))
try:
    execute()
    raise AssertionError("Unexpected schema must fail closed")
except ValueError:
    pass
assert calls == []

ns["frappe"] = fake_frappe("marinademo.frappe.cloud")
execute()
assert len(calls) == 2
mapping, update = calls[0]
assert update is True
fields = mapping["Alhamrani Transaction"]
assert len(fields) == 1
field = fields[0]
assert field["fieldname"] == "custom_bank_verified_transaction_time"
assert field["fieldtype"] == "Time"
assert field["insert_after"] == "pan"
assert field["read_only"] == 1
assert field["no_copy"] == 1
assert "bank-reported" in field["description"].lower()
assert calls[1] == ("cache", {"doctype": "Alhamrani Transaction"})
assert "response_json" not in source
assert "frappe.db.set_value" not in source
assert "frappe.db.commit" not in source
print("Demo-only bank verified transaction time patch checks passed")
