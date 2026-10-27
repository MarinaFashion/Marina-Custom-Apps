from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, now_datetime
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

from marina_custom_apps.pos_reconciliation.bank_statement_reconciliation_service import (
    parse_pos_statement_text,
)

IMPORT_DOCTYPE = "Marina Bank Statement Import"
TXN_DOCTYPE = "Marina Bank Statement Transaction"
MAX_ERRORS = 300
CHUNK = 500

HEADER_ALIASES = {
    "processing_date": ["Processing Date", "Date"],
    "transaction_description": ["Transaction Description"],
    "description": ["Description"],
    "description_extra": ["Description Extra"],
    "reference_number": ["Reference", "Reference Number"],
    "remarks": ["Remarks"],
    "debit": ["Debit", "Withdrawal"],
    "credit": ["Credit", "Deposit"],
    "balance": ["Balance"],
}

REQUIRED = ("processing_date", "description", "debit", "credit", "balance")


def _normalize_header(value):
    return re.sub(r"[\s_\-\/\\.:()\[\]]+", "", cstr(value).strip().casefold())


HEADER_LOOKUP = {
    _normalize_header(alias): fieldname
    for fieldname, aliases in HEADER_ALIASES.items()
    for alias in aliases
}


def _file_content(file_url):
    file_url = cstr(file_url).strip()
    if not file_url:
        frappe.throw(_("Attach an XLSX bank statement first."))
    if not file_url.lower().endswith(".xlsx"):
        frappe.throw(_("Marina Bank Statement Import currently accepts .xlsx files only."))

    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw(_("Attached file could not be found."))
    file_doc = frappe.get_doc("File", file_name)
    if not frappe.has_permission("File", ptype="read", doc=file_doc):
        frappe.throw(_("You do not have permission to read the attached file."), frappe.PermissionError)
    return file_doc.get_content()


def _read_rows(file_url):
    data = read_xlsx_file_from_attached_file(
        fcontent=_file_content(file_url),
        read_only=True,
    )
    if not data:
        frappe.throw(_("The statement file is empty."))

    header_index = None
    header_map = {}
    for idx, row in enumerate(data[:20]):
        candidate = {}
        for col_idx, cell in enumerate(row):
            fieldname = HEADER_LOOKUP.get(_normalize_header(cell))
            if fieldname and fieldname not in candidate:
                candidate[fieldname] = col_idx
        if "processing_date" in candidate and "description" in candidate and (
            "debit" in candidate or "credit" in candidate
        ):
            header_index = idx
            header_map = candidate
            break

    if header_index is None:
        frappe.throw(
            _(
                "Could not find the SNB statement header. Expected Processing Date, Description, Debit and Credit columns."
            )
        )

    # Reject missing Balance at the document level, before any rows can import.
    # Without it the old source fingerprint silently treated Balance as zero.
    if "balance" not in header_map:
        frappe.throw(_(
            "Missing required Balance column. Export the original bank statement "
            "with its Balance column; no transactions have been imported."
        ))

    rows = []
    for excel_row, raw in enumerate(data[header_index + 1 :], start=header_index + 2):
        if any(cell not in (None, "") for cell in raw):
            if not cstr(_cell(raw, header_map, "balance")).strip():
                frappe.throw(_(
                    "Missing Balance value in Excel row {0}. "
                    "Every statement transaction must include its bank balance."
                ).format(excel_row))
            rows.append((excel_row, raw, header_map))
    return rows


def _cell(raw, header_map, fieldname):
    idx = header_map.get(fieldname)
    if idx is None or idx >= len(raw):
        return None
    return raw[idx]


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = cstr(value).strip()
    if not text:
        raise ValueError(_("Processing Date is required."))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return getdate(text)
    except Exception:
        raise ValueError(_("Invalid Processing Date: {0}").format(text))


def _parse_number(value):
    if value in (None, ""):
        return 0.0
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(_("Invalid numeric value: {0}").format(cstr(value)))
    if not number.is_finite():
        raise ValueError(_("Invalid numeric value: {0}").format(cstr(value)))
    result = float(number)
    if not math.isfinite(result):
        raise ValueError(_("Invalid numeric value: {0}").format(cstr(value)))
    return result


def _source_key(bank_account, row):
    fingerprint = "|".join(
        [
            cstr(bank_account).strip(),
            cstr(row["processing_date"]),
            cstr(row.get("reference_number")).strip(),
            f'{flt(row.get("debit"), 2):.2f}',
            f'{flt(row.get("credit"), 2):.2f}',
            f'{flt(row.get("balance"), 2):.2f}',
            cstr(row.get("transaction_description")).strip(),
            cstr(row.get("description")).strip(),
            cstr(row.get("description_extra")).strip(),
            cstr(row.get("remarks")).strip(),
        ]
    )
    return "MBST-" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:24].upper()


def _normalize_row(import_doc, row_number, raw, header_map):
    values = {
        "processing_date": _parse_date(_cell(raw, header_map, "processing_date")),
        "transaction_description": cstr(_cell(raw, header_map, "transaction_description")).strip() or None,
        "description": cstr(_cell(raw, header_map, "description")).strip() or None,
        "description_extra": cstr(_cell(raw, header_map, "description_extra")).strip() or None,
        "reference_number": cstr(_cell(raw, header_map, "reference_number")).strip() or None,
        "remarks": cstr(_cell(raw, header_map, "remarks")).strip() or None,
        "debit": abs(_parse_number(_cell(raw, header_map, "debit"))),
        "credit": abs(_parse_number(_cell(raw, header_map, "credit"))),
        "balance": _parse_number(_cell(raw, header_map, "balance")),
    }
    if values["debit"] and values["credit"]:
        raise ValueError(_("Both Debit and Credit contain values on the same statement row."))

    text = " ".join(
        value
        for value in [
            values.get("transaction_description"),
            values.get("description"),
            values.get("description_extra"),
            values.get("reference_number"),
            values.get("remarks"),
        ]
        if value
    )
    parsed = parse_pos_statement_text(text)

    gl_account = frappe.db.get_value("Bank Account", import_doc.bank_account, "account")
    currency = (
        frappe.db.get_value("Account", gl_account, "account_currency")
        if gl_account
        else None
    ) or "SAR"

    values.update(
        source_row_no=row_number,
        statement_import=import_doc.name,
        bank_account=import_doc.bank_account,
        currency=currency,
        is_pos_statement_line=1 if parsed else 0,
        statement_code=parsed.statement_code if parsed else None,
        component=parsed.component if parsed else None,
        settlement_number=parsed.settlement_number if parsed else None,
        bank_terminal_reference=parsed.bank_terminal_reference if parsed else None,
        reconciliation_date=parsed.reconciliation_date if parsed else None,
        card_type=parsed.card_type if parsed else None,
        transaction_category="POS Settlement" if parsed else None,
        reconciliation_status="Unreconciled",
        allocated_amount=0,
        remaining_amount=flt(values["debit"] or values["credit"], 2),
    )
    values["source_key"] = _source_key(import_doc.bank_account, values)
    return values


def _financial_identity(row):
    """Strong duplicate candidate: reference and bank balance must both agree."""
    reference = cstr(row.get("reference_number")).strip()
    if not reference or row.get("balance") is None:
        return None
    return (
        cstr(row.get("processing_date")),
        reference,
        f'{flt(row.get("debit"), 2):.2f}',
        f'{flt(row.get("credit"), 2):.2f}',
        f'{flt(row.get("balance"), 2):.2f}',
    )


def _secondary_financial_identity(row):
    """Candidate identity without Balance; not proof of a duplicate.

    Banks can legitimately reuse a reference and amount, with different running
    balances. Such matches require explicit user review instead of auto-deletion.
    """
    reference = cstr(row.get("reference_number")).strip()
    if not reference:
        return None
    return (
        cstr(row.get("processing_date")),
        reference,
        f'{flt(row.get("debit"), 2):.2f}',
        f'{flt(row.get("credit"), 2):.2f}',
    )


def _prior_financial_duplicates(import_doc, rows):
    """Bounded indexed candidates, never a full historical bank-table scan."""
    dated = {}
    for row in rows:
        identity = _financial_identity(row)
        if identity:
            dated.setdefault(identity[0], set()).add(identity[1])
    matches = {}
    secondary_matches = {}
    for date_value, references in dated.items():
        refs = sorted(references)
        for start in range(0, len(refs), CHUNK):
            existing = frappe.get_all(
                TXN_DOCTYPE,
                filters={
                    "bank_account": import_doc.bank_account,
                    "processing_date": date_value,
                    "reference_number": ["in", refs[start:start + CHUNK]],
                },
                fields=["name", "processing_date", "reference_number",
                        "debit", "credit", "balance"],
                limit_page_length=0,
            )
            for prior in existing:
                identity = _financial_identity(prior)
                if identity:
                    matches.setdefault(identity, []).append(prior.name)
                secondary = _secondary_financial_identity(prior)
                if secondary:
                    secondary_matches.setdefault(secondary, []).append(prior)
    return matches, secondary_matches


def _analyze(import_doc):
    parsed = []
    errors = []
    dates = []
    total_debit = 0.0
    total_credit = 0.0

    for row_number, raw, header_map in _read_rows(import_doc.import_file):
        try:
            row = _normalize_row(import_doc, row_number, raw, header_map)
            parsed.append(row)
            dates.append(row["processing_date"])
            total_debit += row["debit"]
            total_credit += row["credit"]
        except Exception as exc:
            errors.append(
                {
                    "row_number": row_number,
                    "category": "Error",
                    "reconciliation_key": "",
                    "message": cstr(exc),
                }
            )

    keys = [row["source_key"] for row in parsed]
    existing = set()
    for start in range(0, len(keys), CHUNK):
        chunk = keys[start : start + CHUNK]
        existing.update(
            frappe.get_all(
                TXN_DOCTYPE,
                filters={"source_key": ["in", chunk]},
                pluck="source_key",
                limit_page_length=0,
            )
        )

    unique_rows = []
    seen_keys = set()
    duplicate_in_file = 0
    for row in parsed:
        key = row["source_key"]
        if key in seen_keys:
            duplicate_in_file += 1
            continue
        seen_keys.add(key)
        unique_rows.append(row)

    new_rows = [row for row in unique_rows if row["source_key"] not in existing]
    duplicate_existing = len(unique_rows) - len(new_rows)

    # Strong identity (including Balance) blocks a duplicate, as before.
    # Secondary identity without Balance flags a possible duplicate for review,
    # even if a description or running balance has changed.
    prior_exact, prior_secondary = _prior_financial_duplicates(import_doc, new_rows)
    seen_financial = {}
    seen_secondary = {}
    for row in new_rows:
        identity = _financial_identity(row)
        secondary = _secondary_financial_identity(row)
        if not secondary:
            continue
        existing_name = (prior_exact.get(identity) or [None])[0]
        earlier_row = seen_financial.get(identity)
        if existing_name or earlier_row:
            counterpart = existing_name or _("source row {0}").format(earlier_row)
            errors.append({
                "row_number": row["source_row_no"],
                "category": "Potential Duplicate",
                "reconciliation_key": cstr(row.get("reference_number")),
                "message": _("Potential duplicate of {0}: same bank account, date, reference, debit, credit and balance. Review the bank source before importing.").format(counterpart),
            })
        else:
            prior_candidates = prior_secondary.get(secondary) or []
            prior_weak = next((
                item.name for item in prior_candidates
                if f'{flt(item.balance, 2):.2f}' != f'{flt(row.get("balance"), 2):.2f}'
            ), None)
            earlier_weak = seen_secondary.get(secondary)
            if prior_weak or (
                earlier_weak and earlier_weak[0] != f'{flt(row.get("balance"), 2):.2f}'
            ):
                counterpart = prior_weak or _("source row {0}").format(earlier_weak[1])
                errors.append({
                    "row_number": row["source_row_no"],
                    "category": "Review Warning",
                    "reconciliation_key": cstr(row.get("reference_number")),
                    "message": _(
                        "Possible duplicate of {0}: bank account, date, reference, "
                        "debit and credit match but Balance differs. Verify these are "
                        "separate bank transactions before approving the import."
                    ).format(counterpart),
                })
        if identity:
            seen_financial[identity] = row["source_row_no"]
        seen_secondary.setdefault(
            secondary, (f'{flt(row.get("balance"), 2):.2f}', row["source_row_no"])
        )
    summary = {
        "total_rows": len(parsed) + len(errors),
        "new_records": len(new_rows),
        "duplicate_records": duplicate_in_file + duplicate_existing,
        "error_records": len(errors),
        "review_warning_records": sum(1 for e in errors if e["category"] == "Review Warning"),
        "pos_statement_lines": sum(1 for row in parsed if row["is_pos_statement_line"]),
        "other_statement_lines": sum(1 for row in parsed if not row["is_pos_statement_line"]),
        "statement_from_date": min(dates) if dates else None,
        "statement_to_date": max(dates) if dates else None,
        "total_debit": flt(total_debit, 2),
        "total_credit": flt(total_credit, 2),
    }
    return summary, new_rows, errors


def _save_summary(doc, summary, status, errors=None):
    values = {
        "status": status,
        "statement_from_date": summary.get("statement_from_date"),
        "statement_to_date": summary.get("statement_to_date"),
        "total_debit": summary.get("total_debit", 0),
        "total_credit": summary.get("total_credit", 0),
        "total_rows": cint(summary.get("total_rows")),
        "duplicate_records": cint(summary.get("duplicate_records")),
        "error_records": cint(summary.get("error_records")),
        "review_warning_records": cint(summary.get("review_warning_records")),
        "pos_statement_lines": cint(summary.get("pos_statement_lines")),
        "other_statement_lines": cint(summary.get("other_statement_lines")),
    }
    for fieldname, value in values.items():
        doc.set(fieldname, value)

    doc.set("errors", [])
    for error in (errors or [])[:MAX_ERRORS]:
        doc.append("errors", error)
    if len(errors or []) > MAX_ERRORS:
        doc.append(
            "errors",
            {
                "category": "Info",
                "message": _("Only the first {0} errors are displayed.").format(MAX_ERRORS),
            },
        )

    doc.flags.ignore_permissions = True
    doc.save()


def validate_import(name):
    doc = frappe.get_doc(IMPORT_DOCTYPE, name)
    doc.check_permission("write")
    summary, _rows, errors = _analyze(doc)
    _save_summary(doc, summary, "Validated", errors)
    return summary


def _bulk_insert(rows, requested_by):
    if not rows:
        return 0
    now = now_datetime()
    fields = [
        "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
        "source_key", "statement_import", "bank_account", "source_row_no", "processing_date",
        "reference_number", "debit", "credit", "balance", "currency",
        "transaction_description", "description", "description_extra", "remarks",
        "is_pos_statement_line", "statement_code", "component", "settlement_number",
        "bank_terminal_reference", "reconciliation_date", "card_type",
        "reconciliation_status", "transaction_category", "allocated_amount", "remaining_amount",
    ]
    values = []
    for row in rows:
        record = {
            "name": row["source_key"],
            "owner": requested_by,
            "creation": now,
            "modified": now,
            "modified_by": requested_by,
            "docstatus": 0,
            "idx": 0,
            **row,
        }
        values.append(tuple(record.get(fieldname) for fieldname in fields))

    frappe.db.bulk_insert(
        TXN_DOCTYPE,
        fields=fields,
        values=values,
        ignore_duplicates=True,
        chunk_size=CHUNK,
    )
    return len(rows)


def _file_digest(file_url):
    content = _file_content(file_url)
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def process_import(name, requested_by, acknowledge_possible_duplicates=False, expected_file_digest=None):
    try:
        doc = frappe.get_doc(IMPORT_DOCTYPE, name)
        if not expected_file_digest or _file_digest(doc.import_file) != expected_file_digest:
            frappe.throw(_("The bank statement file changed after review. Validate it again."))
        summary, rows, errors = _analyze(doc)
        if any(row.get("category") == "Potential Duplicate" for row in errors):
            frappe.throw(_("Potential duplicate transactions detected during import revalidation. No rows were imported."))
        if summary.get("review_warning_records") and not cint(acknowledge_possible_duplicates):
            frappe.throw(_("Possible duplicates must be reviewed and explicitly acknowledged before importing."))
        inserted = _bulk_insert(rows, requested_by)
        summary["inserted_records"] = inserted
        status = "Completed" if not errors else "Completed with Errors"

        doc = frappe.get_doc(IMPORT_DOCTYPE, name)
        _save_summary(doc, summary, status, errors)
        doc.db_set("inserted_records", inserted, update_modified=False)
        doc.db_set("imported_on", now_datetime(), update_modified=False)
        doc.db_set("imported_by", requested_by, update_modified=False)
        if summary.get("review_warning_records"):
            doc.db_set("duplicate_reviewed_by", requested_by, update_modified=False)
            doc.db_set("duplicate_reviewed_on", now_datetime(), update_modified=False)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Marina Bank Statement Import")
        frappe.db.set_value(
            IMPORT_DOCTYPE,
            name,
            {"status": "Failed", "error_records": 1},
            update_modified=True,
        )
        frappe.db.commit()


def start_import(name, acknowledge_possible_duplicates=False):
    doc = frappe.get_doc(IMPORT_DOCTYPE, name)
    doc.check_permission("write")
    if doc.status == "Importing":
        frappe.throw(_("This statement import is already running."))

    summary, _rows, errors = _analyze(doc)
    if any(row.get("category") == "Potential Duplicate" for row in errors):
        _save_summary(doc, summary, "Validated", errors)
        frappe.throw(_("Potential duplicate bank transactions detected. Review the validation details before importing."))
    if summary.get("review_warning_records") and not cint(acknowledge_possible_duplicates):
        frappe.throw(_("Possible duplicates require review and explicit confirmation before importing."))
    expected_file_digest = _file_digest(doc.import_file)
    _save_summary(doc, summary, "Importing", errors)
    requested_by = frappe.session.user
    frappe.enqueue(
        "marina_custom_apps.pos_reconciliation.marina_bank_statement_import_service.process_import",
        queue="long",
        timeout=3600,
        job_name=f"Marina Bank Statement Import {name}",
        name=name,
        requested_by=requested_by,
        acknowledge_possible_duplicates=cint(acknowledge_possible_duplicates),
        expected_file_digest=expected_file_digest,
        enqueue_after_commit=True,
    )
    return {"queued": 1, **summary}


def get_import_status(name):
    doc = frappe.get_doc(IMPORT_DOCTYPE, name)
    doc.check_permission("read")
    return {
        "status": doc.status,
        "inserted_records": doc.inserted_records,
        "duplicate_records": doc.duplicate_records,
        "error_records": doc.error_records,
        "total_rows": doc.total_rows,
    }
