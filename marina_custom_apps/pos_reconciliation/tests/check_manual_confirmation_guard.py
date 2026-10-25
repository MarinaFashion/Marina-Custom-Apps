"""Dependency-free CI checks of the *actual* manual slip classifier and key index.

Extract two pure functions from production source without importing Frappe,
which is not available in the GitHub Actions Python runner. Full reconciliation
unit tests remain in test_manual_confirmation_matching.py for Demo bench.
"""
import ast
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
adapter_source = (ROOT / "alhamrani_adapter.py").read_text()
engine_source = (ROOT / "reconciliation_engine.py").read_text()


def extract_function(source, name, namespace):
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, name
    module = ast.Module(body=matches, type_ignores=[])
    exec(compile(module, f"<extracted {name}>", "exec"), namespace)
    return namespace[name]


adapter_tree = ast.parse(adapter_source)
manual_label = next(
    ast.literal_eval(node.value)
    for node in adapter_tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "MANUAL_SLIP_RESPONSE_MEANING"
            for target in node.targets)
)
is_manual = extract_function(
    adapter_source, "is_manual_slip_confirmation",
    {"cstr": lambda value: "" if value is None else str(value),
     "MANUAL_SLIP_RESPONSE_MEANING": manual_label}
)
assert is_manual("Confirmed manually from terminal slip")
assert is_manual("  CONFIRMED  manually   FROM terminal SLIP ")
assert not is_manual("Approved")
assert not is_manual("")
assert not is_manual(None)

auto_index = extract_function(
    engine_source, "_automatic_alhamrani_keys", {"defaultdict": defaultdict}
)
key = "T1|123456789012|ABC|PURCHASE"
manual = SimpleNamespace(name="manual", reconciliation_key=key,
                         manual_confirmation=True)
normal = SimpleNamespace(name="normal", reconciliation_key=key,
                         manual_confirmation=False)
indexed = auto_index([manual, normal])
assert len(indexed[key]) == 1
assert indexed[key][0].name == "normal"
assert not auto_index([manual])

# Assert actual Frappe source loading feeds the classifier into the matcher,
# and missing source schema fails closed instead of enabling auto-matching.
assert '"response_meaning": ("response_meaning",)' in adapter_source
assert 'missing.append("response_meaning")' in adapter_source
assert 'manual_confirmation=is_manual_slip_confirmation(response_meaning)' in adapter_source
assert 'alh_by_key = _automatic_alhamrani_keys(alhamrani_rows)' in engine_source
assert 'if bank.name in manual_links:' in engine_source
assert 'Manual confirmation: approved link required' in engine_source
print("Manual slip classification and auto-match exclusion checks passed")
