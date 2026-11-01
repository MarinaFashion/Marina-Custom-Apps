"""Release 7. Controlled one-time ERPNext Item Template and Size Variant creation.

Preview is read-only. Confirm revalidates under a parent lock and creates all
Items plus immutable audit in one Frappe request transaction.
"""
import hashlib
import hmac
import json
import re
import time

import frappe
from marina_custom_apps.design_management.security.role_access import require_action
from frappe.utils import cint
from marina_custom_apps.design_management.item_field_mapping import SYSTEM_FIELDS, validate_item_field_mappings
from marina_custom_apps.design_management.setup.size_reference import get_size_catalog

MAX_VARIANTS = 40
SAFE_SIZE = re.compile(r"^[A-Za-z0-9]{1,12}$")


def _deny(message):
    frappe.throw(message, frappe.PermissionError)


def _authorize(design):
    user = frappe.session.user
    if user == "Guest" or not frappe.has_permission("Design Code", "read", doc=design):
        _deny("Not allowed to read this Design Code")
    if not frappe.has_permission("Design Code", "write", doc=design):
        _deny("Design Code write permission required")
    if not frappe.has_permission("Item", "create", user=user):
        _deny("ERPNext Item creation permission required")


def _lock_design(name):
    rows = frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                         (name,), as_dict=True)
    if not rows:
        frappe.throw("Design Code does not exist")


def _selected(design, production_key):
    matches = [r for r in design.get("production_items") or []
               if r.production_key == production_key]
    if len(matches) != 1:
        frappe.throw("Select one existing Production Item")
    row = matches[0]
    allocations = [r for r in design.get("production_size_breakdown") or []
                   if r.production_key == production_key and cint(r.qty) > 0]
    if not allocations or len(allocations) > MAX_VARIANTS:
        frappe.throw("Select between 1 and {} Size allocations with positive quantity".format(MAX_VARIANTS))
    sizes = [r.size for r in allocations]
    if len(set(sizes)) != len(sizes):
        frappe.throw("Duplicate Size allocations")
    return row, allocations


def _configuration():
    settings = frappe.get_single("Design Management Settings")
    group = settings.get("item_creation_item_group")
    uom = settings.get("item_creation_stock_uom")
    if not group or not frappe.db.exists("Item Group", group):
        frappe.throw("Configure a valid Item Group in Design Management Settings")
    if not uom or not frappe.db.exists("UOM", uom):
        frappe.throw("Configure a valid Stock UOM in Design Management Settings")
    rows = [r for r in (settings.get("item_field_mappings") or []) if cint(r.is_active)]
    validate_item_field_mappings(rows)
    return group, uom, rows


def _fields(design, production_row, mappings):
    result = {"Template": {}, "Variant": {}}
    for row in mappings:
        source = design if row.source_doctype == "Design Code" else production_row
        value = source.get(row.source_field)
        if cint(row.required_for_creation) and value in (None, ""):
            frappe.throw("Required mapping is empty: {}.{}".format(row.source_doctype, row.source_field))
        if value in (None, ""):
            continue
        for scope in (("Template", "Variant") if row.apply_to == "Both" else (row.apply_to,)):
            if row.target_field in SYSTEM_FIELDS:
                frappe.throw("Protected ERPNext Item mapping target: " + row.target_field)
            result[scope][row.target_field] = value
    result["Template"].setdefault("item_name", production_row.item_code)
    result["Variant"].setdefault("item_name", production_row.item_code)
    return result


def _size_rows(template_code, allocations):
    abbr_to_value, _ = get_size_catalog()
    result = []
    for allocation in allocations:
        abbr = allocation.size
        if not SAFE_SIZE.fullmatch(abbr or "") or abbr not in abbr_to_value:
            frappe.throw("Size abbreviation is missing, invalid, or not in ERPNext Size: " + str(abbr))
        result.append({"abbr": abbr, "value": abbr_to_value[abbr],
                       "item_code": template_code + "-" + abbr,
                       "barcode": template_code + "-" + abbr,
                       "qty": cint(allocation.qty)})
    codes = [r["item_code"] for r in result]
    if len(set(codes)) != len(codes) or any(len(code) > 140 for code in codes):
        frappe.throw("Invalid or duplicate generated variant codes")
    return result


def _check_collisions(template_code, size_rows):
    codes = [template_code] + [r["item_code"] for r in size_rows]
    existing = frappe.get_all("Item", filters={"item_code": ["in", codes]},
                              pluck="item_code", limit_page_length=len(codes))
    if existing:
        frappe.throw("ERPNext Item Code already exists: " + ", ".join(existing[:10]))
    barcodes = [r["barcode"] for r in size_rows]
    found = frappe.get_all("Item Barcode", filters={"barcode": ["in", barcodes]},
                           fields=["barcode"], limit_page_length=len(barcodes))
    if found:
        frappe.throw("ERPNext Barcode already exists: " + ", ".join(r.barcode for r in found[:10]))


def _payload(design, production_key, check_collision=True):
    row, allocations = _selected(design, production_key)
    group, uom, mappings = _configuration()
    template = (row.item_code or "").strip()
    if not template or len(template) > 120 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", template):
        frappe.throw("The planned Item Code must contain only letters, numbers, underscore, and hyphen")
    sizes = _size_rows(template, allocations)
    if check_collision:
        _check_collisions(template, sizes)
    mapped = _fields(design, row, mappings)
    return {"design_code": design.name, "production_key": production_key,
            "template_code": template, "item_group": group, "stock_uom": uom,
            "size_attribute": "Size", "sizes": sizes, "mapped": mapped,
            "color_name": row.color_name or ""}


def _fingerprint(payload, design, issued_at):
    secret = frappe.conf.get("encryption_key")
    if not secret:
        frappe.throw("Site encryption key is required to confirm Item creation")
    content = json.dumps({"payload": payload, "modified": str(design.modified),
                          "user": frappe.session.user, "issued_at": issued_at}, sort_keys=True,
                         default=str, separators=(",", ":"))
    return hmac.new(secret.encode(), content.encode(), hashlib.sha256).hexdigest()


def _existing_record(key):
    return frappe.db.exists("Design Item Creation", key)


@frappe.whitelist()
def preview_item_creation(design_code, production_key):
    require_action("Create ERPNext Items")
    design = frappe.get_doc("Design Code", design_code)
    _authorize(design)
    if _existing_record(production_key):
        frappe.throw("This Production Item already has an Item creation record; open its audit record")
    payload = _payload(design, production_key)
    issued_at = int(time.time())
    payload["confirmation_token"] = "{}:{}".format(
        issued_at, _fingerprint(payload, design, issued_at))
    return payload


@frappe.whitelist(methods=["POST"])
def confirm_item_creation(design_code, production_key, confirmation_token):
    require_action("Create ERPNext Items")
    if not confirmation_token or not isinstance(confirmation_token, str):
        frappe.throw("Preview and confirmation token required")
    _lock_design(design_code)
    design = frappe.get_doc("Design Code", design_code)
    _authorize(design)
    if _existing_record(production_key):
        frappe.throw("This Production Item was already created. No duplicate items were generated.")
    payload = _payload(design, production_key)
    try:
        issued_text, supplied_signature = confirmation_token.split(":", 1)
        issued_at = int(issued_text)
    except (ValueError, TypeError):
        frappe.throw("Invalid confirmation token; reopen Preview")
    if not (0 <= time.time() - issued_at <= 300):
        frappe.throw("Preview expired; reopen Preview before confirming")
    expected = _fingerprint(payload, design, issued_at)
    if not hmac.compare_digest(expected, supplied_signature):
        frappe.throw("Preview is stale: reopen the preview before confirming")

    from erpnext.controllers.item_variant import create_variant

    template_code = payload["template_code"]
    template = frappe.get_doc({
        "doctype": "Item", "item_code": template_code,
        "item_name": payload["mapped"]["Template"].get("item_name", template_code),
        "item_group": payload["item_group"], "stock_uom": payload["stock_uom"],
        "has_variants": 1, "attributes": [{"attribute": "Size"}],
    })
    for name, value in payload["mapped"]["Template"].items():
        template.set(name, value)
    template.insert()
    generated = []
    for size in payload["sizes"]:
        variant = create_variant(template.name, {"Size": size["value"]})
        variant.item_code = size["item_code"]
        for name, value in payload["mapped"]["Variant"].items():
            variant.set(name, value)
        # Item Name is the complete generated Size Variant Code, not the template name.
        # Apply this AFTER mapped fields so a mapping cannot overwrite it.
        variant.item_name = size["item_code"]
        variant.item_group = payload["item_group"]
        variant.stock_uom = payload["stock_uom"]
        variant.append("barcodes", {"barcode": size["barcode"], "uom": payload["stock_uom"]})
        variant.insert()
        generated.append({"item_code": variant.name, "size": size["abbr"],
                          "barcode": size["barcode"]})
    audit = frappe.get_doc({
        "doctype": "Design Item Creation", "name": production_key,
        "production_key": production_key, "design_code": design.name,
        "template_item": template.name, "created_by": frappe.session.user,
        "created_on": frappe.utils.now_datetime(),
        "variant_snapshot": json.dumps(generated, sort_keys=True),
        "mapping_snapshot": json.dumps(payload, sort_keys=True, default=str),
    })
    audit.insert(ignore_permissions=True)
    return {"template": template.name, "variants": generated,
            "audit_record": audit.name}


def prevent_linked_mutation(current, before):
    """Protect generated Item identities; never synchronize later planning edits."""
    previous = {row.production_key: row for row in (before.get("production_items") or [])}
    current_rows = {row.production_key: row for row in (current.get("production_items") or [])}
    keys = list(previous)
    if not keys:
        return
    linked = frappe.get_all("Design Item Creation",
        filters={"production_key": ["in", keys]}, pluck="production_key",
        limit_page_length=len(keys))
    for key in linked:
        old = previous[key]
        now = current_rows.get(key)
        if not now or old.item_code != now.item_code:
            frappe.throw("Cannot delete or rename a Production Item after Item creation")
        def sizes(doc):
            return {row.size for row in (doc.get("production_size_breakdown") or [])
                    if row.production_key == key}
        if sizes(before) != sizes(current):
            frappe.throw("Cannot change generated Size identities after Item creation. Quantities may still change without syncing Items.")


@frappe.whitelist()
def get_created_item_references(design_code):
    design = frappe.get_doc("Design Code", design_code)
    if not frappe.has_permission("Design Code", "read", doc=design):
        _deny("Not allowed to read this Design Code")
    rows = frappe.get_all("Design Item Creation",
        filters={"design_code": design_code},
        fields=["name", "production_key", "template_item", "variant_snapshot", "created_on"],
        order_by="created_on desc", limit_page_length=200)
    result = []
    for row in rows:
        try:
            variants = json.loads(row.variant_snapshot or "[]")
        except (TypeError, ValueError):
            variants = []
        result.append({"audit_record": row.name, "production_key": row.production_key,
                       "template_item": row.template_item, "created_on": row.created_on,
                       "variants": variants})
    return result


@frappe.whitelist()
def get_production_item_statuses(design_code):
    """Read-only, batch Item existence. No Item creation or audit mutation."""
    design = frappe.get_doc("Design Code", design_code)
    if not frappe.has_permission("Design Code", "read", doc=design):
        _deny("Not permitted to read this Design Code")
    items = (design.get("production_items") or [])[:200]
    allocations = design.get("production_size_breakdown") or []
    expected = {}
    all_codes = set()
    for row in items:
        template = (row.item_code or "").strip()
        if not template or not row.production_key:
            continue
        sizes = {a.size for a in allocations
                 if a.production_key == row.production_key and cint(a.qty) > 0 and a.size}
        variants = {template + "-" + size for size in sizes}
        codes = variants | {template}
        expected[row.production_key] = (template, codes, len(variants))
        all_codes.update(codes)
    existing = set()
    names = sorted(all_codes)
    for offset in range(0, len(names), 250):
        chunk = names[offset:offset + 250]
        existing.update(frappe.get_all(
            "Item", filters={"item_code": ["in", chunk]}, pluck="item_code",
            limit_page_length=len(chunk)))
    out = []
    for row in items:
        if row.production_key not in expected:
            continue
        template, codes, size_count = expected[row.production_key]
        present = codes & existing
        state = ("Not Created" if not present else
                 "Created" if present == codes else "Partially Created")
        out.append({"production_key": row.production_key, "item_code": template,
                    "status": state, "created_count": len(present),
                    "expected_count": len(codes),
                    "created_variants": max(0, len(present) - int(template in present)),
                    "expected_variants": size_count})
    return out


@frappe.whitelist()
def production_item_creation_status(design_code):
    """Read-only batched Item existence by planned code and selected Size.

    Status is determined by actual ERPNext Items, never solely audit records.
    """
    design = frappe.get_doc("Design Code", design_code)
    if not frappe.has_permission("Design Code", "read", doc=design):
        _deny("Not allowed to read this Design Code")
    planned = list(design.get("production_items") or [])
    if len(planned) > 200:
        frappe.throw("Too many Production Items for status display")
    allocations = list(design.get("production_size_breakdown") or [])
    if len(allocations) > 5000:
        frappe.throw("Too many Size allocations for status display")
    sizes = {}
    for allocation in allocations:
        if cint(allocation.qty) > 0:
            sizes.setdefault(allocation.production_key, set()).add(allocation.size)
    wanted = {}
    codes = set()
    for row in planned:
        if not row.production_key or not row.item_code:
            continue
        expected = [row.item_code] + [
            row.item_code + "-" + size for size in sorted(sizes.get(row.production_key, set()))
        ]
        wanted[row.production_key] = expected
        codes.update(expected)
    existing = set()
    sorted_codes = sorted(codes)
    for n in range(0, len(sorted_codes), 250):
        batch = sorted_codes[n:n + 250]
        existing.update(frappe.get_all("Item",
            filters={"item_code": ["in", batch]},
            pluck="item_code", limit_page_length=len(batch)))
    result = {}
    for key, expected in wanted.items():
        count = sum(code in existing for code in expected)
        status = ("Created" if count == len(expected)
                  else "Not Created" if not count else "Partially Created")
        result[key] = {"status": status, "existing": count,
                       "expected": len(expected)}
    return result
