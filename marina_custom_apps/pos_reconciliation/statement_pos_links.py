"""Materialize read-only POS reconciliation references on imported bank statement rows.

One statement component row refers to a settlement, potentially containing many
POS Reconciliation Records. This is a display projection, not accounting evidence.
Maintain it within the same database transaction as settlement reconciliation.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

import frappe
from frappe.utils import cstr, now_datetime

STATEMENT = "Marina Bank Statement Transaction"
RECORD = "POS Reconciliation Record"
CHILD = "Marina Statement POS Record"
PARENTFIELD = "pos_reconciliation_records"
STATUS_LABELS = {
    "Fully Matching": "Fully Matched",
    "Bank Only - Settled": "Bank Only - Settled",
}
BATCH_SIZE = 400


def _chunks(values, size=BATCH_SIZE):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _display_status(actual_status):
    """Translate the canonical record status into the requested display label."""
    return STATUS_LABELS.get(cstr(actual_status).strip())


def _canonical_details(settlement, record_lookup):
    """One row per contributing eligible POS record, not per Bank POS source row."""
    details = {}
    unsupported = 0

    for txn in settlement.get("transactions") or []:
        name = cstr(txn.reconciliation_record).strip()
        if not name:
            continue
        record = record_lookup.get(name)
        if not record:
            unsupported += 1
            continue
        display_status = _display_status(record.match_status)
        if not display_status:
            unsupported += 1
            continue

        profile = cstr(record.pos_profile or txn.pos_profile).strip()
        details[name] = (name, profile, display_status)

    detail_rows = sorted(details.values(), key=lambda row: row[0])
    profiles = {row[1] for row in detail_rows if row[1]}
    # Empty profile indicates unknown/multiple stores, never an arbitrary store.
    single_profile = (
        next(iter(profiles))
        if detail_rows and len(profiles) == 1
        and all(row[1] for row in detail_rows) and not unsupported
        else None
    )
    return detail_rows, single_profile, unsupported


def _child_name(statement_name, record_name):
    return "MSPR-" + hashlib.sha256(
        f"{statement_name}|{record_name}".encode("utf-8")
    ).hexdigest()[:25]


def sync_statement_pos_links(statement_rows, settlements, evidence):
    """Idempotently refresh statement-linked POS records after final status updates.

    Only statement rows in the reconciliation execution are touched. The normal
    POS settlement transaction and record tables remain the authoritative data.
    Do not invoke this for all historical statement rows after every execution.
    """
    if not statement_rows:
        return {"statements_checked": 0, "details_changed": 0, "unsupported": 0}

    target_by_name = {row.name: row for row in statement_rows}
    names = sorted(target_by_name)
    record_names = {
        cstr(txn.reconciliation_record).strip()
        for key, doc in settlements.items()
        if doc.status == "Fully Reconciled" and evidence.get(key)
        for txn in (doc.get("transactions") or [])
        if cstr(txn.reconciliation_record).strip()
    }

    record_lookup = {}
    for chunk in _chunks(sorted(record_names)):
        for doc in frappe.get_all(
            RECORD,
            filters={"name": ["in", chunk]},
            fields=["name", "pos_profile", "match_status"],
            limit_page_length=0,
        ):
            record_lookup[doc.name] = doc

    desired = {name: ([], None) for name in names}
    unsupported_count = 0
    for key, doc in settlements.items():
        statement_evidence = evidence.get(key) or []
        if not statement_evidence or doc.status != "Fully Reconciled":
            continue
        details, profile, unsupported = _canonical_details(doc, record_lookup)
        unsupported_count += unsupported
        for row in statement_evidence:
            if row.name in desired:
                desired[row.name] = (details, profile)

    existing_children = defaultdict(list)
    existing_profiles = {}
    for chunk in _chunks(names):
        for row in frappe.get_all(
            CHILD,
            filters={
                "parenttype": STATEMENT,
                "parentfield": PARENTFIELD,
                "parent": ["in", chunk],
            },
            fields=["parent", "pos_reconciliation_record", "pos_profile", "match_status"],
            limit_page_length=0,
        ):
            existing_children[row.parent].append((
                cstr(row.pos_reconciliation_record),
                cstr(row.pos_profile),
                cstr(row.match_status),
            ))
        for row in frappe.get_all(
            STATEMENT,
            filters={"name": ["in", chunk]},
            fields=["name", "pos_profile"],
            limit_page_length=0,
        ):
            existing_profiles[row.name] = cstr(row.pos_profile)

    changed = {}
    profiles_to_update = defaultdict(list)
    for name in names:
        detail_rows, profile = desired[name]
        existing = sorted(existing_children.get(name, []))
        if existing != detail_rows:
            changed[name] = detail_rows
        if existing_profiles.get(name, "") != cstr(profile):
            profiles_to_update[profile].append(name)

    # Delete/replace only changed statement child groups; rerunning an identical
    # period does not churn thousands of rows or force unnecessary SQL writes.
    if changed:
        for chunk in _chunks(sorted(changed)):
            frappe.db.delete(CHILD, {
                "parenttype": STATEMENT,
                "parentfield": PARENTFIELD,
                "parent": ["in", chunk],
            })

        owner = frappe.session.user or "Administrator"
        now = now_datetime()
        columns = [
            "name", "owner", "creation", "modified", "modified_by", "docstatus",
            "idx", "parent", "parenttype", "parentfield",
            "pos_reconciliation_record", "pos_profile", "match_status",
        ]
        values = []
        for parent in sorted(changed):
            for index, (record_name, profile, status) in enumerate(changed[parent], start=1):
                values.append((
                    _child_name(parent, record_name), owner, now, now, owner, 0,
                    index, parent, STATEMENT, PARENTFIELD,
                    record_name, profile or None, status,
                ))
        if values:
            frappe.db.bulk_insert(CHILD, fields=columns, values=values, chunk_size=1000)

    # Group by POS Profile to keep update count bounded for large statement runs.
    for profile, ids in profiles_to_update.items():
        for chunk in _chunks(ids):
            placeholders = ", ".join(["%s"] * len(chunk))
            frappe.db.sql(
                f"UPDATE `tabMarina Bank Statement Transaction` "
                f"SET pos_profile = %s WHERE name IN ({placeholders})",
                tuple([profile] + chunk),
            )

    if unsupported_count:
        frappe.logger("pos_reconciliation").warning(
            "%s POS settlement transactions have no eligible Fully Matching / "
            "Bank Only - Settled record status for statement detail projection",
            unsupported_count,
        )

    return {
        "statements_checked": len(names),
        "details_changed": len(changed),
        "unsupported": unsupported_count,
    }
