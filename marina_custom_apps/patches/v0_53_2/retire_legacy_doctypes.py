"""Retire verified-empty POS legacy DocTypes without touching financial records."""

from __future__ import annotations

import json

import frappe
from frappe import _

from marina_custom_apps.patches.v0_53_2.preflight_legacy_cleanup import (
    LEGACY_DOCTYPES,
    assert_legacy_tables_empty,
    assert_no_running_pos_executions,
)

WORKSPACE = "POS Reconciliation"
LEGACY_LABELS = {
    "POS Bank Manual Clearance",
    "Pos Bank Manual Clearance",
    "POS Bank Statement Reconciliation",
}


def _assert_no_schema_links():
    for doctype in LEGACY_DOCTYPES:
        for source, owner_field in (
            ("DocField", "parent"),
            ("Custom Field", "dt"),
        ):
            references = frappe.get_all(
                source,
                filters={
                    "options": doctype,
                    "fieldtype": ["in", ["Link", "Table", "Table MultiSelect"]],
                },
                fields=[owner_field, "fieldname"],
                limit_page_length=1,
            )
            if references:
                row = references[0]
                frappe.throw(
                    _("POS cleanup refused: {0} is still referenced by "
                      "{1}.{2} ({3}).").format(
                          doctype, row.get(owner_field), row.fieldname, source
                      )
                )


def _clean_workspace():
    if not frappe.db.exists("Workspace", WORKSPACE):
        return

    doc = frappe.get_doc("Workspace", WORKSPACE)
    changed = False
    obsolete_labels = set(LEGACY_LABELS)

    for row in list(doc.get("shortcuts") or []):
        if row.type == "DocType" and row.link_to in LEGACY_DOCTYPES:
            if row.label:
                obsolete_labels.add(row.label)
            doc.get("shortcuts").remove(row)
            changed = True
        elif (
            row.type == "DocType"
            and row.link_to == "Bank Statement Reconciliation"
            and row.doc_view
        ):
            # Frappe v15 Workspace Shortcut does not support "Form".
            row.doc_view = ""
            changed = True

    for row in list(doc.get("links") or []):
        if (
            row.type == "Link"
            and row.link_type == "DocType"
            and row.link_to in LEGACY_DOCTYPES
        ):
            doc.get("links").remove(row)
            changed = True

    try:
        blocks = json.loads(doc.content or "[]")
    except (TypeError, ValueError):
        blocks = None  # Do not overwrite malformed user Workspace content.

    if isinstance(blocks, list):
        filtered = [
            block for block in blocks
            if not (
                isinstance(block, dict)
                and block.get("type") == "shortcut"
                and (block.get("data") or {}).get("shortcut_name") in obsolete_labels
            )
        ]
        if len(filtered) != len(blocks):
            doc.content = json.dumps(filtered, separators=(",", ":"))
            changed = True

    if changed:
        doc.flags.ignore_links = True
        doc.save(ignore_permissions=True)


def execute():
    # Guard twice: before source DocTypes sync (preflight) and immediately
    # before metadata deletion. Refuse to delete a populated legacy table.
    assert_legacy_tables_empty()
    assert_no_running_pos_executions()
    _assert_no_schema_links()
    _clean_workspace()

    for doctype in LEGACY_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            frappe.delete_doc(
                "DocType", doctype, force=True,
                ignore_permissions=True, ignore_missing=True,
            )
    frappe.clear_cache()
