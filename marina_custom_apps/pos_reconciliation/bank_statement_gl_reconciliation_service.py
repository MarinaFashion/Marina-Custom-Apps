from __future__ import annotations

from collections import defaultdict
import re

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.bank_reconciliation_exclusion_service import active_excluded_names, _source_key

STATEMENT_DOCTYPE = "Marina Bank Statement Transaction"
MATCH_DOCTYPE = "Bank Statement Reconciliation Match"
GL_CHILD_DOCTYPE = "Bank Statement Reconciliation GL Row"
DEFAULT_TOLERANCE = 0.01


def _normalize_reference(value):
    """Normalize references for exact business matching without using dates."""
    return re.sub(r"[^A-Z0-9]+", "", cstr(value).strip().upper())


def _bank_signed_amount(row):
    return flt(row.credit, 2) - flt(row.debit, 2)


def _gl_signed_amount(row):
    return flt(row.debit, 2) - flt(row.credit, 2)


def _bank_description(row):
    values = [
        row.get("transaction_description"),
        row.get("description"),
        row.get("description_extra"),
        row.get("remarks"),
    ]
    return " | ".join(cstr(value).strip() for value in values if cstr(value).strip())


def _bank_gl_account(bank_account):
    account = frappe.db.get_value("Bank Account", bank_account, "account")
    if not account:
        frappe.throw(_("Bank Account {0} is not linked to an ERPNext Account.").format(bank_account))
    return account


def _already_reconciled_gl_entries():
    if not frappe.db.exists("DocType", GL_CHILD_DOCTYPE):
        return set()
    return set(
        frappe.get_all(
            GL_CHILD_DOCTYPE,
            filters={"parenttype": MATCH_DOCTYPE},
            pluck="gl_entry",
            limit_page_length=0,
        )
    )


def _pos_generated_journal_entries():
    if not frappe.db.exists("DocType", "POS Accounting Posting"):
        return set()
    return set(
        value
        for value in frappe.get_all(
            "POS Accounting Posting",
            filters={"journal_entry": ["is", "set"]},
            pluck="journal_entry",
            limit_page_length=0,
        )
        if value
    )


def _voucher_reference_map(rows):
    payment_names = list({row.voucher_no for row in rows if row.voucher_type == "Payment Entry" and row.voucher_no})
    journal_names = list({row.voucher_no for row in rows if row.voucher_type == "Journal Entry" and row.voucher_no})
    out = {}

    if payment_names:
        meta = frappe.get_meta("Payment Entry")
        fields = ["name"]
        if meta.has_field("reference_no"):
            fields.append("reference_no")
        for row in frappe.get_all("Payment Entry", filters={"name": ["in", payment_names]}, fields=fields, limit_page_length=0):
            out[("Payment Entry", row.name)] = cstr(row.get("reference_no")).strip()

    if journal_names:
        meta = frappe.get_meta("Journal Entry")
        fields = ["name"]
        if meta.has_field("cheque_no"):
            fields.append("cheque_no")
        for row in frappe.get_all("Journal Entry", filters={"name": ["in", journal_names]}, fields=fields, limit_page_length=0):
            out[("Journal Entry", row.name)] = cstr(row.get("cheque_no")).strip()

    return out


def _load_bank_rows(bank_account):
    excluded_bank = active_excluded_names(bank_account, "Bank Statement")
    bank_filters = {
        "bank_account": bank_account,
        "is_pos_statement_line": 0,
        "reconciliation_status": "Unreconciled",
    }
    if excluded_bank:
        bank_filters["name"] = ["not in", list(excluded_bank)]
    rows = frappe.get_all(
        STATEMENT_DOCTYPE,
        filters=bank_filters,
        fields=[
            "name",
            "processing_date",
            "reference_number",
            "transaction_description",
            "description",
            "description_extra",
            "remarks",
            "debit",
            "credit",
        ],
        order_by="processing_date asc, name asc",
        limit_page_length=0,
    )
    output = []
    for row in rows:
        output.append(
            frappe._dict(
                name=row.name,
                date=row.processing_date,
                transaction_id=row.name,
                reference_number=cstr(row.reference_number).strip(),
                normalized_reference=_normalize_reference(row.reference_number),
                description=_bank_description(row),
                amount=_bank_signed_amount(row),
            )
        )
    return output


def _load_gl_rows(bank_account):
    account = _bank_gl_account(bank_account)
    excluded_gl = _already_reconciled_gl_entries()
    excluded_gl.update(active_excluded_names(bank_account, "GL Entry"))
    excluded_pos_jes = _pos_generated_journal_entries()
    gl_filters = {
        "account": account,
        "voucher_type": ["in", ["Payment Entry", "Journal Entry"]],
        "is_cancelled": 0,
    }
    if excluded_gl:
        gl_filters["name"] = ["not in", list(excluded_gl)]

    rows = frappe.get_all(
        "GL Entry",
        filters=gl_filters,
        fields=[
            "name",
            "posting_date",
            "voucher_type",
            "voucher_no",
            "debit",
            "credit",
            "remarks",
        ],
        order_by="posting_date asc, creation asc, name asc",
        limit_page_length=0,
    )

    rows = [
        row
        for row in rows
        if row.name not in excluded_gl
        and not (row.voucher_type == "Journal Entry" and row.voucher_no in excluded_pos_jes)
    ]
    references = _voucher_reference_map(rows)

    output = []
    for row in rows:
        reference = references.get((row.voucher_type, row.voucher_no), "")
        output.append(
            frappe._dict(
                name=row.name,
                date=row.posting_date,
                transaction_id=row.name,
                voucher_type=row.voucher_type,
                voucher_no=row.voucher_no,
                reference_number=reference,
                normalized_reference=_normalize_reference(reference),
                description=cstr(row.remarks).strip(),
                amount=_gl_signed_amount(row),
            )
        )
    return output


def _auto_reference_matches(bank_rows, gl_rows, tolerance):
    bank_groups = defaultdict(list)
    gl_groups = defaultdict(list)

    for row in bank_rows:
        if row.normalized_reference:
            bank_groups[row.normalized_reference].append(row)
    for row in gl_rows:
        if row.normalized_reference:
            gl_groups[row.normalized_reference].append(row)

    matches = []
    used_bank = set()
    used_gl = set()

    for reference in sorted(set(bank_groups).intersection(gl_groups)):
        bank_group = bank_groups[reference]
        gl_group = gl_groups[reference]
        bank_total = flt(sum(row.amount for row in bank_group), 2)
        gl_total = flt(sum(row.amount for row in gl_group), 2)
        difference = flt(bank_total - gl_total, 2)
        if abs(difference) > tolerance:
            continue

        matches.append(
            {
                "match_type": "Auto Reference",
                "reference_number": bank_group[0].reference_number or gl_group[0].reference_number,
                "bank_amount": bank_total,
                "gl_amount": gl_total,
                "difference": difference,
                "bank_rows": [dict(row) for row in bank_group],
                "gl_rows": [dict(row) for row in gl_group],
            }
        )
        used_bank.update(row.name for row in bank_group)
        used_gl.update(row.name for row in gl_group)

    return matches, used_bank, used_gl



def _workspace_filters(from_date=None, to_date=None, reference=None):
    start = getdate(from_date) if from_date else None
    end = getdate(to_date) if to_date else None
    if start and end and start > end:
        frappe.throw(_("From Date must be on or before To Date."))
    reference = cstr(reference or "").strip()
    if len(reference) > 140:
        frappe.throw(_("Reference filter is too long."))
    return {"from_date": start, "to_date": end, "reference": reference.casefold()}


def _visible_row(row, filters):
    date = getdate(row.date)
    if filters["from_date"] and date < filters["from_date"]:
        return False
    if filters["to_date"] and date > filters["to_date"]:
        return False
    query = filters["reference"]
    if not query:
        return True
    amount = "{:.2f}".format(flt(row.amount, 2))
    return (query in cstr(row.reference_number).casefold()
            or query in cstr(row.description).casefold()
            or query in amount
            or query in amount.replace(",", ""))


def _reconciled_summary(bank_account, filters):
    """Summarize saved general-bank reconciliation evidence, not POS settlements."""
    bank_sql = """
        SELECT COUNT(*) AS transaction_count,
               COALESCE(SUM(COALESCE(credit, 0) - COALESCE(debit, 0)), 0) AS amount
        FROM `tabMarina Bank Statement Transaction`
        WHERE bank_account = %s AND is_pos_statement_line = 0
          AND reconciliation_status = 'Reconciled'
          AND bank_statement_reconciliation_match IS NOT NULL
          AND bank_statement_reconciliation_match != ''
    """
    gl_sql = """
        SELECT COUNT(*) AS transaction_count, COALESCE(SUM(g.amount), 0) AS amount
        FROM `tabBank Statement Reconciliation GL Row` g
        INNER JOIN `tabBank Statement Reconciliation Match` m ON m.name = g.parent
        WHERE m.bank_account = %s AND m.status = 'Reconciled'
          AND g.parenttype = 'Bank Statement Reconciliation Match'
          AND g.parentfield = 'gl_rows'
    """
    bank_args, gl_args = [bank_account], [bank_account]
    if filters["from_date"]:
        bank_sql += " AND processing_date >= %s"
        gl_sql += " AND g.posting_date >= %s"
        bank_args.append(filters["from_date"])
        gl_args.append(filters["from_date"])
    if filters["to_date"]:
        bank_sql += " AND processing_date <= %s"
        gl_sql += " AND g.posting_date <= %s"
        bank_args.append(filters["to_date"])
        gl_args.append(filters["to_date"])
    if filters["reference"]:
        # INSTR treats % and _ as literal text, rather than SQL LIKE wildcards.
        bank_sql += """ AND (
            INSTR(LOWER(COALESCE(reference_number, '')), %s) > 0
            OR INSTR(LOWER(CONCAT_WS(' ', transaction_description, description, description_extra, remarks)), %s) > 0
            OR INSTR(CAST(ROUND(COALESCE(credit, 0) - COALESCE(debit, 0), 2) AS CHAR), %s) > 0
        )"""
        gl_sql += """ AND (
            INSTR(LOWER(COALESCE(g.reference_number, '')), %s) > 0
            OR INSTR(LOWER(COALESCE(g.description, '')), %s) > 0
            OR INSTR(CAST(ROUND(g.amount, 2) AS CHAR), %s) > 0
        )"""
        bank_args.extend([filters["reference"]] * 3)
        gl_args.extend([filters["reference"]] * 3)
    bank = frappe.db.sql(bank_sql, tuple(bank_args), as_dict=True)[0]
    gl = frappe.db.sql(gl_sql, tuple(gl_args), as_dict=True)[0]
    return {
        "reconciled_bank_transactions": int(bank.transaction_count or 0),
        "reconciled_gl_transactions": int(gl.transaction_count or 0),
        "reconciled_bank_amount": flt(bank.amount, 2),
        "reconciled_gl_amount": flt(gl.amount, 2),
    }


def get_workspace(bank_account, tolerance=None, from_date=None, to_date=None, reference=None):
    bank_account = cstr(bank_account).strip()
    if not bank_account:
        return {"bank_rows": [], "gl_rows": [], "matches": [], "counts": {}, "summary": {}}

    filters = _workspace_filters(from_date, to_date, reference)
    tolerance = abs(flt(tolerance if tolerance not in (None, "") else DEFAULT_TOLERANCE, 2))
    bank_rows = _load_bank_rows(bank_account)
    gl_rows = _load_gl_rows(bank_account)

    # Match over the complete dataset: reference grouping must not depend on date.
    auto_matches, _used_bank, _used_gl = _auto_reference_matches(bank_rows, gl_rows, tolerance)
    visible_bank = [row for row in bank_rows if _visible_row(row, filters)]
    visible_gl = [row for row in gl_rows if _visible_row(row, filters)]
    # Never save rows hidden by filters as part of an automatically prepared group.
    visible_matches = [
        match for match in auto_matches
        if all(_visible_row(frappe._dict(row), filters) for row in match["bank_rows"])
        and all(_visible_row(frappe._dict(row), filters) for row in match["gl_rows"])
    ]
    used_bank = {row["name"] for match in visible_matches for row in match["bank_rows"]}
    used_gl = {row["name"] for match in visible_matches for row in match["gl_rows"]}
    remaining_bank = [dict(row) for row in visible_bank if row.name not in used_bank]
    remaining_gl = [dict(row) for row in visible_gl if row.name not in used_gl]
    # Screen-only row numbers, independently numbered after filtering.
    for idx, row in enumerate(remaining_bank, start=1):
        row["row_no"] = idx
    for idx, row in enumerate(remaining_gl, start=1):
        row["row_no"] = idx

    summary = _reconciled_summary(bank_account, filters)
    summary.update({
        # Prepared matches remain unreconciled until the Save action succeeds.
        "unreconciled_bank_transactions": len(visible_bank),
        "unreconciled_gl_transactions": len(visible_gl),
        "unreconciled_bank_amount": flt(sum(row.amount for row in visible_bank), 2),
        "unreconciled_gl_amount": flt(sum(row.amount for row in visible_gl), 2),
    })
    return {
        "bank_rows": remaining_bank,
        "gl_rows": remaining_gl,
        "matches": visible_matches,
        "summary": summary,
        "counts": {
            "unreconciled_bank": len(remaining_bank),
            "unreconciled_gl": len(remaining_gl),
            "auto_matches": len(visible_matches),
            "auto_bank_rows": len(used_bank),
            "auto_gl_rows": len(used_gl),
        },
    }


def _current_bank_rows(names, bank_account):
    names = list(dict.fromkeys(names or []))
    if not names:
        return []
    rows = frappe.get_all(
        STATEMENT_DOCTYPE,
        filters={
            "name": ["in", names],
            "bank_account": bank_account,
            "is_pos_statement_line": 0,
            "reconciliation_status": "Unreconciled",
        },
        fields=[
            "name","processing_date","reference_number","transaction_description","description",
            "description_extra","remarks","debit","credit",
        ],
        limit_page_length=0,
    )
    if len(rows) != len(names):
        frappe.throw(_("One or more Bank Statement rows are no longer available for reconciliation. Refresh the screen."))
    if active_excluded_names(bank_account, "Bank Statement").intersection(names):
        frappe.throw(_("One or more Bank Statement rows have been excluded. Refresh the screen."))
    return rows


def _current_gl_rows(names, bank_account):
    names = list(dict.fromkeys(names or []))
    if not names:
        return []
    account = _bank_gl_account(bank_account)
    excluded = _already_reconciled_gl_entries()
    if excluded.intersection(names):
        frappe.throw(_("One or more GL Entries were already reconciled. Refresh the screen."))
    if active_excluded_names(bank_account, "GL Entry").intersection(names):
        frappe.throw(_("One or more GL Entries have been excluded. Refresh the screen."))

    rows = frappe.get_all(
        "GL Entry",
        filters={
            "name": ["in", names],
            "account": account,
            "voucher_type": ["in", ["Payment Entry", "Journal Entry"]],
            "is_cancelled": 0,
        },
        fields=["name","posting_date","voucher_type","voucher_no","debit","credit","remarks"],
        limit_page_length=0,
    )
    if len(rows) != len(names):
        frappe.throw(_("One or more GL Entries are no longer available for reconciliation. Refresh the screen."))

    excluded_pos_jes = _pos_generated_journal_entries()
    if any(row.voucher_type == "Journal Entry" and row.voucher_no in excluded_pos_jes for row in rows):
        frappe.throw(_("POS Reconciliation generated Journal Entries cannot be used in general bank reconciliation."))
    return rows



def _lock_and_check_not_excluded(source_type, names):
    """Lock source rows and the exclusion state to prevent concurrent saves/exclusions."""
    if source_type == "Bank Statement":
        source_table = "tabMarina Bank Statement Transaction"
    else:
        source_table = "tabGL Entry"
    for name in sorted(names):
        frappe.db.sql(
            f"SELECT name FROM `{source_table}` WHERE name = %s FOR UPDATE",
            (name,),
        )
        key = _source_key(source_type, name)
        state = frappe.db.sql(
            "SELECT status FROM `tabBank Reconciliation Exclusion` WHERE source_key = %s FOR UPDATE",
            (key,),
            as_dict=True,
        )
        if state and state[0].status == "Excluded":
            frappe.throw(_("A selected transaction was excluded while reconciliation was being prepared. Refresh the screen."))


def save_matches(bank_account, matches, tolerance=None):
    bank_account = cstr(bank_account).strip()
    if not bank_account:
        frappe.throw(_("Bank Account is required."))
    if isinstance(matches, str):
        matches = frappe.parse_json(matches)
    matches = matches or []
    if not matches:
        frappe.throw(_("There are no reconciliation matches to save."))

    tolerance = abs(flt(tolerance if tolerance not in (None, "") else DEFAULT_TOLERANCE, 2))
    now = now_datetime()
    user = frappe.session.user
    created = []
    consumed_bank = set()
    consumed_gl = set()

    for proposal in matches:
        bank_names = list(dict.fromkeys(proposal.get("bank_names") or []))
        gl_names = list(dict.fromkeys(proposal.get("gl_names") or []))
        if not bank_names or not gl_names:
            frappe.throw(_("Every reconciliation match requires Bank and GL rows."))
        if consumed_bank.intersection(bank_names) or consumed_gl.intersection(gl_names):
            frappe.throw(_("The same Bank or GL row cannot be used in more than one match."))

        _lock_and_check_not_excluded("Bank Statement", bank_names)
        _lock_and_check_not_excluded("GL Entry", gl_names)
        bank_rows = _current_bank_rows(bank_names, bank_account)
        gl_rows = _current_gl_rows(gl_names, bank_account)

        match_type = cstr(proposal.get("match_type")).strip()
        if match_type not in {"Auto Reference", "Manual TR", "Manual Group"}:
            frappe.throw(_("Unsupported reconciliation Match Type."))
        # Fetch references only once per group; also reused for saved GL audit rows.
        ref_map = _voucher_reference_map(gl_rows)
        if match_type == "Auto Reference":
            references = {_normalize_reference(row.reference_number) for row in bank_rows}
            references.update(
                _normalize_reference(ref_map.get((row.voucher_type, row.voucher_no)))
                for row in gl_rows
            )
            if len(references) != 1 or not next(iter(references)):
                frappe.throw(_("Automatic matching requires the same non-empty reference on all Bank and GL rows."))

        bank_total = flt(sum(_bank_signed_amount(row) for row in bank_rows), 2)
        gl_total = flt(sum(_gl_signed_amount(row) for row in gl_rows), 2)
        difference = flt(bank_total - gl_total, 2)
        if abs(difference) > tolerance:
            frappe.throw(
                _("Match does not balance. Bank {0}, GL {1}, difference {2}.").format(
                    bank_total, gl_total, difference
                )
            )

        references = [cstr(row.reference_number).strip() for row in bank_rows if cstr(row.reference_number).strip()]
        doc = frappe.new_doc(MATCH_DOCTYPE)
        doc.bank_account = bank_account
        doc.match_type = match_type
        doc.reference_number = references[0] if references else cstr(proposal.get("reference_number")).strip()
        doc.status = "Reconciled"
        doc.bank_amount = bank_total
        doc.gl_amount = gl_total
        doc.difference = difference
        doc.reconciled_on = now
        doc.reconciled_by = user

        for row in bank_rows:
            doc.append(
                "bank_rows",
                {
                    "statement_transaction": row.name,
                    "processing_date": row.processing_date,
                    "reference_number": row.reference_number,
                    "description": _bank_description(row),
                    "amount": _bank_signed_amount(row),
                },
            )

        for row in gl_rows:
            doc.append(
                "gl_rows",
                {
                    "gl_entry": row.name,
                    "posting_date": row.posting_date,
                    "voucher_type": row.voucher_type,
                    "voucher_no": row.voucher_no,
                    "reference_number": ref_map.get((row.voucher_type, row.voucher_no), ""),
                    "description": row.remarks,
                    "amount": _gl_signed_amount(row),
                },
            )

        doc.flags.ignore_permissions = True
        doc.insert()
        created.append(doc.name)

        category = "Other"
        voucher_types = {row.voucher_type for row in gl_rows}
        if voucher_types == {"Payment Entry"}:
            category = "Payment Entry"
        elif voucher_types == {"Journal Entry"}:
            category = "Journal Entry"

        for row in bank_rows:
            amount = abs(_bank_signed_amount(row))
            frappe.db.set_value(
                STATEMENT_DOCTYPE,
                row.name,
                {
                    "reconciliation_status": "Reconciled",
                    "transaction_category": category,
                    "allocated_amount": amount,
                    "remaining_amount": 0,
                    "bank_statement_reconciliation_match": doc.name,
                    "reconciled_on": now,
                    "reconciled_by": user,
                },
                update_modified=False,
            )

        consumed_bank.update(bank_names)
        consumed_gl.update(gl_names)

    return {
        "created_matches": created,
        "match_count": len(created),
        "bank_rows_reconciled": len(consumed_bank),
        "gl_rows_reconciled": len(consumed_gl),
    }
