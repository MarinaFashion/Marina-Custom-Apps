"""Read-only Link targets synchronized from ERPNext's Item Attribute > Size.

ERPNext Item Attribute Value is a child DocType whose document name is not the
abbreviation. 'Design Size Reference' is ONLY a searchable, synchronized
projection. The ERPNext Size attribute remains the single source of truth.

Sync runs when Item Attribute 'Size' is saved and after bench migrate.
Existing saved full descriptions are converted to abbreviations *together*
with the corresponding Production Size Breakdown references, never discarded.
"""
from collections import defaultdict

import frappe


SOURCE_ATTRIBUTE = "Size"
REFERENCE_DOCTYPE = "Design Size Reference"


def get_size_catalog():
    """Return (abbr -> description, description -> abbreviation) with safeguards."""
    if not frappe.db.exists("Item Attribute", SOURCE_ATTRIBUTE):
        return {}, {}
    rows = frappe.get_all(
        "Item Attribute Value",
        filters={"parent": SOURCE_ATTRIBUTE, "parenttype": "Item Attribute"},
        fields=["abbr", "attribute_value"],
        order_by="idx asc",
        limit_page_length=500,
    )
    by_abbr = {}
    by_label = {}
    folded = set()
    for row in rows:
        abbr = (row.abbr or "").strip()
        label = (row.attribute_value or "").strip()
        if not abbr or not label:
            frappe.throw("ERPNext Size Item Attribute contains a blank abbreviation or description")
        if len(abbr) > 140:
            frappe.throw("ERPNext Size abbreviation is too long: " + abbr[:80])
        if abbr.casefold() in folded:
            frappe.throw("ERPNext Size contains duplicate abbreviations: " + abbr)
        folded.add(abbr.casefold())
        if label in by_label and by_label[label] != abbr:
            frappe.throw("ERPNext Size contains ambiguous descriptions: " + label)
        by_abbr[abbr] = label
        by_label[label] = abbr
    return by_abbr, by_label


def sync_size_references(migrate_existing=False):
    """Synchronize only the Size catalog, without creating a second editable master."""
    if not frappe.db.exists("DocType", REFERENCE_DOCTYPE):
        return

    by_abbr, by_label = get_size_catalog()
    if not frappe.db.exists("Item Attribute", SOURCE_ATTRIBUTE):
        # Never assume an absent ERPNext master is an instruction to delete history.
        if migrate_existing:
            _check_unrecognized_existing({}, {})
        return

    existing = {
        row.name: row
        for row in frappe.get_all(
            REFERENCE_DOCTYPE,
            fields=["name", "description", "is_active"],
            limit_page_length=1000,
        )
    }
    for abbr, description in by_abbr.items():
        current = existing.get(abbr)
        if not current:
            frappe.get_doc({
                "doctype": REFERENCE_DOCTYPE,
                "abbreviation": abbr,
                "description": description,
                "is_active": 1,
            }).insert(ignore_permissions=True)
        elif current.description != description or not current.is_active:
            frappe.db.set_value(
                REFERENCE_DOCTYPE, abbr,
                {"description": description, "is_active": 1},
                update_modified=False,
            )

    # Keep old Link destinations to protect existing saved documents, but
    # exclude any abbreviation no longer in ERPNext Size from new selection.
    for name, record in existing.items():
        if name not in by_abbr and record.is_active:
            frappe.db.set_value(
                REFERENCE_DOCTYPE, name, "is_active", 0,
                update_modified=False,
            )

    if migrate_existing:
        _migrate_saved_sizes(by_abbr, by_label)


def sync_when_size_changed(doc, method=None):
    """Frappe Item Attribute.on_update hook; never sync unrelated attributes."""
    if doc.name == SOURCE_ATTRIBUTE:
        sync_size_references()


def _mapped_code(value, by_abbr, by_label):
    value = (value or "").strip()
    return value if value in by_abbr else by_label.get(value)


def _check_unrecognized_existing(by_abbr, by_label):
    """Preflight existing rows, so a failed migration cannot partially rewrite Size data."""
    tables = [
        ("Marina Design Size", "sizes"),
        ("Design Production Size", "production_size_breakdown"),
    ]
    changes = []
    unknown = []
    duplicates = []
    for doctype, parentfield in tables:
        if not frappe.db.exists("DocType", doctype):
            continue
        rows = frappe.get_all(
            doctype,
            filters={"parenttype": "Design Code", "parentfield": parentfield},
            fields=["name", "parent", "size"] + (["production_key"] if doctype == "Design Production Size" else []) +
                   (["size_description"] if doctype == "Marina Design Size" else []),
            limit_page_length=0,
        )
        seen = defaultdict(set)
        for row in rows:
            code = _mapped_code(row.size, by_abbr, by_label)
            if not code:
                unknown.append("{} / {} / {}".format(doctype, row.parent, row.size))
                continue
            group = (row.parent, row.production_key) if doctype == "Design Production Size" else row.parent
            if code in seen[group]:
                duplicates.append("{} / {} / {}".format(doctype, row.parent, code))
            seen[group].add(code)
            updates = {}
            if row.size != code:
                updates["size"] = code
            if doctype == "Marina Design Size" and row.size_description != by_abbr[code]:
                updates["size_description"] = by_abbr[code]
            if updates:
                changes.append((doctype, row.name, updates))
    if unknown or duplicates:
        messages = []
        if unknown:
            messages.append("Unrecognized existing Sizes: " + ", ".join(unknown[:10]))
        if duplicates:
            messages.append("Duplicate Size assignments: " + ", ".join(duplicates[:10]))
        details = "; ".join(messages)
        frappe.throw(
            "Size Link migration requires data review. " + details +
            ". No Size rows have been rewritten."
        )
    return changes


def _migrate_saved_sizes(by_abbr, by_label):
    """Idempotent migration including per-item production allocations."""
    for doctype, name, updates in _check_unrecognized_existing(by_abbr, by_label):
        frappe.db.set_value(doctype, name, updates, update_modified=False)
