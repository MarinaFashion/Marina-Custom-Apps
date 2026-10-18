"""Archive orphaned historical POS statement-run summaries, then retire old tables.

This patch is specifically for sites where v0.53.7 DocType metadata was removed
but its guarded v0.53.2 patches were marked skipped. It does not touch imported
bank transactions, reconciliation records, settlements, or Journal Entries.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe import _

from marina_custom_apps.patches.v0_53_2.preflight_legacy_cleanup import (
    LEGACY_DOCTYPES,
    assert_no_running_pos_executions,
)
from marina_custom_apps.patches.v0_53_2.retire_legacy_doctypes import (
    _assert_no_schema_links,
    _clean_workspace,
)

STATEMENT_RUN = "POS Bank Statement Reconciliation"
MAX_ARCHIVABLE_ROWS = 10
REFERENCE_FIELDS = (
    ("POS Bank Settlement", "reconciliation_run"),
    ("POS Reconciliation Record", "bank_statement_reconciliation"),
    ("Marina Bank Statement Transaction", "pos_reconciliation_run"),
)


def _legacy_rows(doctype):
    if not frappe.db.table_exists(doctype):
        return []
    return frappe.db.sql(
        "SELECT * FROM `tab{0}` ORDER BY name".format(doctype),
        as_dict=True,
    )


def _assert_unlinked(rows):
    for row in rows:
        for doctype, field in REFERENCE_FIELDS:
            if not frappe.db.table_exists(doctype):
                frappe.throw(
                    _("POS cleanup cannot verify the {0} source table.").format(doctype)
                )
            if frappe.db.sql(
                "SELECT name FROM `tab{0}` WHERE `{1}` = %s LIMIT 1".format(
                    doctype, field
                ),
                (row.name,),
            ):
                frappe.throw(
                    _("Historical statement run {0} has a linked {1}.{2} record; "
                      "review before cleanup.").format(row.name, doctype, field)
                )


def _archive_old_statement_runs(rows):
    if not rows:
        return None

    if len(rows) > MAX_ARCHIVABLE_ROWS:
        frappe.throw(
            _("POS legacy statement table contains {0} records. "
              "Automatic archival is limited to {1}; inspect the history first.").format(
                  len(rows), MAX_ARCHIVABLE_ROWS
              )
        )

    _assert_unlinked(rows)

    payload = {
        "archive_format": "marina-pos-legacy-statement-run-v1",
        "source_doctype": STATEMENT_RUN,
        "records": [dict(row) for row in rows],
        "record_count": len(rows),
    }
    content = frappe.as_json(payload, indent=2).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    filename = "marina-pos-legacy-statement-runs-{0}.json".format(digest[:20])

    matches = frappe.get_all(
        "File",
        filters={
            "file_name": filename,
            "attached_to_doctype": "POS Reconciliation Run",
            "attached_to_name": "POS Reconciliation Run",
            "is_private": 1,
        },
        fields=["name"],
        limit_page_length=1,
    )

    if matches:
        file = frappe.get_doc("File", matches[0].name)
        try:
            existing = file.get_content()
        except Exception:
            frappe.throw(
                _("Legacy archive {0} is not readable; cleanup stopped.").format(
                    file.name
                )
            )
        if isinstance(existing, str):
            existing = existing.encode("utf-8")
        if hashlib.sha256(existing).hexdigest() != digest:
            frappe.throw(
                _("Legacy archive checksum mismatch for File {0}.").format(
                    file.name
                )
            )
        return file.name

    from frappe.utils.file_manager import save_file

    file = save_file(
        filename,
        content,
        "POS Reconciliation Run",
        "POS Reconciliation Run",
        is_private=1,
    )
    if not file.name or not frappe.db.exists("File", file.name):
        frappe.throw(_("Could not confirm saved POS legacy archive."))

    # Verify that the file is readable and intact before any DROP TABLE DDL.
    saved = frappe.get_doc("File", file.name).get_content()
    if isinstance(saved, str):
        saved = saved.encode("utf-8")
    if hashlib.sha256(saved).hexdigest() != digest:
        frappe.throw(_("POS legacy archive verification failed; cleanup stopped."))

    return file.name


def execute():
    assert_no_running_pos_executions()
    _assert_no_schema_links()

    for doctype in LEGACY_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            frappe.throw(
                _("POS legacy DocType {0} is still registered; "
                  "finish metadata migration before physical table cleanup.").format(
                    doctype
                )
            )

    # Review all table content BEFORE archiving or running DDL.
    remaining = {doctype: _legacy_rows(doctype) for doctype in LEGACY_DOCTYPES}
    for doctype in LEGACY_DOCTYPES:
        if doctype != STATEMENT_RUN and remaining[doctype]:
            frappe.throw(
                _("Unexpected rows in legacy table {0}; manual review required.").format(
                    doctype
                )
            )

    _archive_old_statement_runs(remaining[STATEMENT_RUN])
    _clean_workspace()

    # This patch intentionally removes physical tables only after verified
    # archival/no-link checks. It never drops an active source or finance table.
    for doctype in LEGACY_DOCTYPES:
        if frappe.db.table_exists(doctype):
            frappe.db.sql_ddl("DROP TABLE `tab{0}`".format(doctype))

    frappe.clear_cache()
