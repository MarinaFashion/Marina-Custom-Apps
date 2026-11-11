"""Static sanity checks for the POS Reconciliation document Connections tab.

Run: python marina_custom_apps/pos_reconciliation/tests/check_pos_connections_tab.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
metadata = json.loads(
    (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.json").read_text(encoding="utf-8")
)
js = (ROOT / "doctype/pos_reconciliation_run/pos_reconciliation_run.js").read_text(encoding="utf-8")
fields = {field["fieldname"]: field for field in metadata["fields"]}
assert fields["connections_tab"]["fieldtype"] == "Tab Break"
assert fields["connections_tab"]["label"] == "Connections"
assert fields["connections_html"]["fieldtype"] == "HTML"
assert metadata["field_order"][-3:] == [
    "connections_tab", "connections_section", "connections_html"
]
assert 'function pos_recon_render_connections(frm, has_results)' in js
assert 'pos_recon_render_connections(frm, has_results);' in js
assert '}, __("Connections"));' not in js
assert 'frm.add_custom_button(__("Create Journal Entries")' in js
assert 'frm.add_custom_button(__("Close Selected Period")' in js
for key in ("records", "import_pos", "import_statement", "locks", "history"):
    assert 'case "' + key + '":' in js
assert 'field.$wrapper.off("click.pos_recon_connections")' in js
print("POS Connections tab checks passed.")
