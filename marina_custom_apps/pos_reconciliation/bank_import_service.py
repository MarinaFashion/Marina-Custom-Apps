from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, now_datetime
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

from marina_custom_apps.pos_reconciliation.doctype.bank_pos_transaction.bank_pos_transaction import (
    normalize_transaction_type,
    try_build_reconciliation_key,
)
from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

BANK_DOCTYPE = "Bank POS Transaction"
TOOL_DOCTYPE = "POS Bank Import"
WORKSPACE = "POS Reconciliation"
SHORTCUT_LABEL = "Bank Import Tool"
MAX_ERROR_ROWS = 500
QUERY_CHUNK = 500
INSERT_CHUNK = 500

IMMUTABLE_IMPORT_FIELDS = (
    "bank_mid", "site_id", "terminal_id", "rrn", "auth_code",
    "transaction_type", "card_type", "masked_card_number",
    "transaction_date", "transaction_time", "transaction_amount",
)

MUTABLE_IMPORT_FIELDS = (
    "transaction_status", "rejection_reason", "cashback_amount",
    "balance_status", "balance_date", "balance_time",
    "fee_rate", "fee_amount", "vat_amount",
    "settled", "settlement_date", "settlement_amount",
    "settlement_number", "pos_reconciliation_number",
)

ALL_SOURCE_FIELDS = IMMUTABLE_IMPORT_FIELDS + MUTABLE_IMPORT_FIELDS

HEADER_ALIASES = {
    "bank_mid": ["Mid", "Bank MID", "MID", "رقم الموقع"],
    "site_id": ["Retailer", "Site ID", "Merchant ID", "Site ID / Merchant ID"],
    "terminal_id": ["Terminal", "Terminal ID", "رقم الجهاز"],
    "rrn": ["Sequence Number", "RRN", "Reference Number", "RRN / Reference Number", "رقم المرجع"],
    "auth_code": ["Authorization number", "Authorization Number", "Auth Code", "رمز التفويض"],
    "card_type": ["Card Type", "نوع البطاقة"],
    "masked_card_number": ["Card Number", "Masked Card Number", "رقم البطاقة"],
    "transaction_type": ["Transaction Type", "نوع العملية"],
    "transaction_date": ["Transaction Date", "تاريخ العملية"],
    "transaction_time": ["Transaction Time", "وقت العملية"],
    "transaction_amount": ["Transaction Amount", "مبلغ العملية"],
    "transaction_status": ["transaction Status", "Transaction Status", "Status", "حالة العملية"],
    "rejection_reason": ["Rejection Reasons", "Rejection Reason", "أسباب الرفض"],
    "cashback_amount": ["Cashback Amount", "مبلغ الاسترداد النقدي"],
    "balance_status": ["Reconciled", "Balanced", "Balance Status", "الموازنة"],
    "balance_date": ["Reconciled Date", "Balance Date", "تاريخ الموازنة"],
    "balance_time": ["Reconciled Time", "Balance Time", "وقت الموازنة"],
    "fee_rate": ["Fees Percentage", "Fee Rate", "Commission %", "نسبة الرسوم"],
    "fee_amount": ["Fee Amount", "Commission Amount", "مبلغ الرسوم"],
    "vat_amount": ["VAT", "VAT on Fee", "[SA]VAT"],
    "settled": ["Settled", "تسوية"],
    "settlement_date": ["Settled Date", "Settlement Date", "تاريخ التسوية"],
    "settlement_amount": ["Settlement Amount", "مبلغ التسوية"],
    "settlement_number": ["reconciliation Number", "Reconciliation Number", "Settlement Number", "رقم التسوية"],
    "pos_reconciliation_number": ["POS Reconciliation Number"],
}

REQUIRED_FIELDS = (
    "bank_mid", "terminal_id", "rrn", "auth_code",
    "transaction_type", "transaction_date", "transaction_time", "transaction_amount",
)

DATE_FIELDS = ("transaction_date", "balance_date", "settlement_date")
TIME_FIELDS = ("transaction_time", "balance_time")
MONEY_FIELDS = ("transaction_amount", "cashback_amount", "fee_amount", "vat_amount", "settlement_amount")
PERCENT_FIELDS = ("fee_rate",)
CHECK_FIELDS = ("balance_status", "settled")
TEXT_FIELDS = tuple(
    fieldname for fieldname in ALL_SOURCE_FIELDS
    if fieldname not in DATE_FIELDS + TIME_FIELDS + MONEY_FIELDS + PERCENT_FIELDS + CHECK_FIELDS
)


def _check_permission():
    if not frappe.has_permission(TOOL_DOCTYPE, ptype="write"):
        frappe.throw(_("You do not have permission to use the Bank Import Tool."), frappe.PermissionError)
    if not cint(frappe.db.get_single_value(TOOL_DOCTYPE, "tool_enabled")):
        frappe.throw(_("The Bank Import Tool is disabled."))


def _normalize_header(value):
    text = cstr(value).strip().casefold()
    return re.sub(r"[\s_\-\/\\.:()\[\]]+", "", text)


HEADER_LOOKUP = {
    _normalize_header(alias): fieldname
    for fieldname, aliases in HEADER_ALIASES.items()
    for alias in aliases
}


def _file_content(file_url):
    file_url = cstr(file_url).strip()
    if not file_url:
        frappe.throw(_("Select a Bank Excel file first."))
    if not file_url.lower().endswith(".xlsx"):
        frappe.throw(_("Bank Import Tool currently accepts .xlsx files only."))

    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw(_("Attached file could not be found: {0}").format(file_url))

    file_doc = frappe.get_doc("File", file_name)
    if not frappe.has_permission("File", ptype="read", doc=file_doc):
        frappe.throw(_("You do not have permission to read the attached file."), frappe.PermissionError)
    return file_doc.get_content()


def _read_rows(file_url):
    data = read_xlsx_file_from_attached_file(fcontent=_file_content(file_url), read_only=True)
    if not data:
        frappe.throw(_("The Excel file is empty."))

    header_index = None
    header_map = {}
    for idx, row in enumerate(data[:20]):
        candidate = {}
        for col_index, cell in enumerate(row):
            fieldname = HEADER_LOOKUP.get(_normalize_header(cell))
            if fieldname and fieldname not in candidate:
                candidate[fieldname] = col_index
        if all(fieldname in candidate for fieldname in REQUIRED_FIELDS):
            header_index = idx
            header_map = candidate
            break

    if header_index is None:
        missing_labels = ", ".join(HEADER_ALIASES[fieldname][0] for fieldname in REQUIRED_FIELDS)
        frappe.throw(_("Could not find a valid Bank header row. Required columns include: {0}.").format(missing_labels))

    rows = []
    for excel_index, raw in enumerate(data[header_index + 1:], start=header_index + 2):
        if not any(cell not in (None, "") for cell in raw):
            continue
        rows.append((excel_index, raw, header_map))
    return rows


def _parse_date(value, field_label):
    if value in (None, ""):
        return None, 0
    if isinstance(value, datetime):
        return value.date(), 0
    if isinstance(value, date):
        return value, 0

    text = cstr(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date(), 1
        except ValueError:
            raise ValueError(_("{0}: invalid compact date {1}").format(field_label, text))

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date(), 0
        except ValueError:
            pass

    try:
        return getdate(text), 0
    except Exception:
        raise ValueError(_("{0}: invalid date {1}").format(field_label, text))


def _parse_time(value, field_label):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, (int, float)) and 0 <= float(value) < 1:
        seconds = int(round(float(value) * 86400)) % 86400
        return str(timedelta(seconds=seconds))

    text = cstr(value).strip().split(".", 1)[0]
    if text.isdigit() and len(text) in (4, 6):
        fmt = "%H%M" if len(text) == 4 else "%H%M%S"
        try:
            return datetime.strptime(text, fmt).time().isoformat()
        except ValueError:
            pass
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time().isoformat()
        except ValueError:
            pass
    raise ValueError(_("{0}: invalid time {1}").format(field_label, text))


def _parse_number(value, field_label, required=False):
    if value in (None, ""):
        if required:
            raise ValueError(_("{0} is required.").format(field_label))
        return None

    raw_value = value
    if isinstance(value, bool):
        raise ValueError(_("{0}: invalid numeric value {1}").format(field_label, cstr(raw_value)))

    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if not value:
            if required:
                raise ValueError(_("{0} is required.").format(field_label))
            return None

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(_("{0}: invalid numeric value {1}").format(field_label, cstr(raw_value)))

    if not number.is_finite():
        raise ValueError(_("{0}: invalid numeric value {1}").format(field_label, cstr(raw_value)))

    numeric = float(number)
    if not math.isfinite(numeric):
        raise ValueError(_("{0}: invalid numeric value {1}").format(field_label, cstr(raw_value)))

    return numeric


def _parse_check(value, field_label):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if cint(value) else 0

    text = cstr(value).strip().casefold()
    if text in {"1", "yes", "y", "true", "reconciled", "settled", "نعم"}:
        return 1
    if text in {"0", "no", "n", "false", "not reconciled", "not settled", "لا"}:
        return 0
    raise ValueError(_("{0}: invalid Yes/No value {1}").format(field_label, cstr(value)))


def _cell(raw, header_map, fieldname):
    index = header_map.get(fieldname)
    if index is None or index >= len(raw):
        return None
    return raw[index]


def _normalize_row(row_number, raw, header_map):
    output = {}
    conversions = 0

    for fieldname in TEXT_FIELDS:
        value = _cell(raw, header_map, fieldname)
        output[fieldname] = cstr(value).strip() if value not in (None, "") else None

    output["transaction_type"] = normalize_transaction_type(output.get("transaction_type"))
    if output.get("card_type"):
        output["card_type"] = output["card_type"].upper()

    for fieldname in DATE_FIELDS:
        value, converted = _parse_date(_cell(raw, header_map, fieldname), HEADER_ALIASES[fieldname][0])
        output[fieldname] = value
        conversions += converted

    for fieldname in TIME_FIELDS:
        output[fieldname] = _parse_time(_cell(raw, header_map, fieldname), HEADER_ALIASES[fieldname][0])

    for fieldname in MONEY_FIELDS:
        output[fieldname] = _parse_number(
            _cell(raw, header_map, fieldname),
            HEADER_ALIASES[fieldname][0],
            required=(fieldname == "transaction_amount"),
        )

    for fieldname in PERCENT_FIELDS:
        output[fieldname] = _parse_number(_cell(raw, header_map, fieldname), HEADER_ALIASES[fieldname][0])

    for fieldname in CHECK_FIELDS:
        output[fieldname] = _parse_check(_cell(raw, header_map, fieldname), HEADER_ALIASES[fieldname][0])

    for fieldname in REQUIRED_FIELDS:
        if output.get(fieldname) in (None, ""):
            raise ValueError(_("{0} is required.").format(HEADER_ALIASES[fieldname][0]))

    key, key_error = try_build_reconciliation_key(
        output.get("terminal_id"), output.get("rrn"), output.get("auth_code"), output.get("transaction_type")
    )
    if key_error:
        raise ValueError(key_error)

    output["reconciliation_key"] = key
    output["row_number"] = row_number
    output["date_conversions"] = conversions
    return output


def _chunks(values, size=QUERY_CHUNK):
    values = list(values or [])
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _existing_map(keys):
    result = {}
    fields = ["name", "reconciliation_key", *ALL_SOURCE_FIELDS]
    for chunk in _chunks(keys):
        rows = frappe.get_all(
            BANK_DOCTYPE,
            filters={"reconciliation_key": ["in", chunk]},
            fields=fields,
            limit_page_length=0,
        )
        result.update({row.reconciliation_key: row for row in rows})
    return result


def _same(fieldname, left, right):
    if fieldname in DATE_FIELDS:
        return (getdate(left) if left else None) == (getdate(right) if right else None)
    if fieldname in TIME_FIELDS:
        try:
            left = _parse_time(left, fieldname) if left not in (None, "") else None
        except ValueError:
            left = cstr(left).strip()
        try:
            right = _parse_time(right, fieldname) if right not in (None, "") else None
        except ValueError:
            right = cstr(right).strip()
        return left == right
    if fieldname in MONEY_FIELDS + PERCENT_FIELDS:
        if left in (None, "") and right in (None, ""):
            return True
        return abs(flt(left) - flt(right)) <= 0.0001
    if fieldname in CHECK_FIELDS:
        return cint(left) == cint(right)
    return cstr(left).strip() == cstr(right).strip()


def _classify(normalized_rows):
    existing = _existing_map([row["reconciliation_key"] for row in normalized_rows])
    seen = {}
    classified = []

    for row in normalized_rows:
        key = row["reconciliation_key"]
        if key in seen:
            classified.append({
                "action": "error", "row": row,
                "message": _("Duplicate reconciliation key in file; first occurrence is row {0}.").format(seen[key]),
            })
            continue
        seen[key] = row["row_number"]

        old = existing.get(key)
        if not old:
            classified.append({"action": "insert", "row": row})
            continue

        conflicts = []
        for fieldname in IMMUTABLE_IMPORT_FIELDS:
            incoming = row.get(fieldname)
            if incoming in (None, "") and fieldname not in REQUIRED_FIELDS:
                continue
            if not _same(fieldname, old.get(fieldname), incoming):
                conflicts.append(HEADER_ALIASES[fieldname][0])

        if conflicts:
            classified.append({
                "action": "conflict", "row": row, "existing": old,
                "message": _("Existing transaction has different immutable source values: {0}.").format(", ".join(conflicts)),
            })
            continue

        updates = {}
        for fieldname in MUTABLE_IMPORT_FIELDS:
            incoming = row.get(fieldname)
            if incoming in (None, ""):
                continue
            if not _same(fieldname, old.get(fieldname), incoming):
                updates[fieldname] = incoming

        if updates:
            classified.append({"action": "update", "row": row, "existing": old, "updates": updates})
        else:
            classified.append({"action": "unchanged", "row": row, "existing": old})

    return classified


def _analyze(file_url):
    parsed = []
    errors = []
    total_rows = 0
    date_conversions = 0

    for row_number, raw, header_map in _read_rows(file_url):
        total_rows += 1
        try:
            row = _normalize_row(row_number, raw, header_map)
            date_conversions += cint(row.pop("date_conversions", 0))
            parsed.append(row)
        except Exception as exc:
            errors.append({"row_number": row_number, "category": "Error", "reconciliation_key": "", "message": cstr(exc)})

    classified = _classify(parsed)
    summary = {
        "total_rows": total_rows, "new_records": 0, "update_records": 0,
        "unchanged_records": 0, "conflict_records": 0, "error_records": len(errors),
        "inserted_records": 0, "updated_records": 0, "skipped_records": 0,
        "date_conversions": date_conversions,
    }

    for item in classified:
        action = item["action"]
        if action == "insert":
            summary["new_records"] += 1
        elif action == "update":
            summary["update_records"] += 1
        elif action == "unchanged":
            summary["unchanged_records"] += 1
        elif action == "conflict":
            summary["conflict_records"] += 1
            errors.append({
                "row_number": item["row"]["row_number"], "category": "Conflict",
                "reconciliation_key": item["row"]["reconciliation_key"], "message": item["message"],
            })
        elif action == "error":
            summary["error_records"] += 1
            errors.append({
                "row_number": item["row"]["row_number"], "category": "Error",
                "reconciliation_key": item["row"]["reconciliation_key"], "message": item["message"],
            })

    return summary, classified, errors


def _save_summary(summary, status, errors=None, processed_by=None):
    doc = frappe.get_single(TOOL_DOCTYPE)
    doc.status = status
    doc.last_processed_on = now_datetime()
    doc.last_processed_by = processed_by or frappe.session.user

    for fieldname in (
        "total_rows", "new_records", "update_records", "unchanged_records",
        "conflict_records", "error_records", "inserted_records", "updated_records",
        "skipped_records", "date_conversions",
    ):
        doc.set(fieldname, cint(summary.get(fieldname, 0)))

    doc.set("errors", [])
    for error in (errors or [])[:MAX_ERROR_ROWS]:
        doc.append("errors", error)
    if len(errors or []) > MAX_ERROR_ROWS:
        doc.append("errors", {
            "category": "Info",
            "message": _("Only the first {0} errors/conflicts are displayed. Total: {1}.").format(MAX_ERROR_ROWS, len(errors)),
        })

    doc.flags.ignore_permissions = True
    doc.save()
    return summary


def validate_import_file(file_url=None):
    _check_permission()
    summary, _classified, errors = _analyze(file_url)
    _save_summary(summary, "Validated", errors)
    return summary


def _bank_name(reconciliation_key):
    digest = hashlib.sha1(reconciliation_key.encode("utf-8")).hexdigest()[:20].upper()
    return f"BPT-{digest}"


def _insert_rows(items, requested_by):
    now = now_datetime()
    fields = [
        "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
        "bank_mid", "site_id", "terminal_id", "rrn", "auth_code", "transaction_type",
        "reconciliation_key", "transaction_date", "transaction_time", "transaction_amount",
        "pos_profile", "transaction_status", "card_type", "masked_card_number",
        "rejection_reason", "cashback_amount", "balance_status", "balance_date", "balance_time",
        "fee_rate", "fee_amount", "vat_amount", "settled", "settlement_date",
        "settlement_amount", "settlement_number", "pos_reconciliation_number", "accounting_status",
    ]
    values = []

    for item in items:
        row = item["row"]
        record = {
            "name": _bank_name(row["reconciliation_key"]),
            "owner": requested_by, "creation": now, "modified": now, "modified_by": requested_by,
            "docstatus": 0, "idx": 0,
            **{fieldname: row.get(fieldname) for fieldname in ALL_SOURCE_FIELDS},
            "reconciliation_key": row["reconciliation_key"],
            "pos_profile": resolve_pos_profile(row["terminal_id"], row["transaction_date"]),
            "balance_status": cint(row.get("balance_status")),
            "settled": cint(row.get("settled")),
            "accounting_status": "Not Eligible",
        }
        values.append(tuple(record.get(fieldname) for fieldname in fields))

    for chunk in _chunks(values, INSERT_CHUNK):
        frappe.db.bulk_insert(BANK_DOCTYPE, fields=fields, values=chunk, ignore_duplicates=False, chunk_size=INSERT_CHUNK)
    return len(values)


def _update_rows(items):
    updated = 0
    updated_names = []
    execution_errors = []

    for item in items:
        row = item["row"]
        old = item["existing"]
        savepoint = f"pos_bank_import_{row['row_number']}"
        frappe.db.savepoint(savepoint)
        try:
            frappe.db.set_value(BANK_DOCTYPE, old.name, item["updates"], update_modified=True)
            updated += 1
            updated_names.append(old.name)
        except Exception as exc:
            frappe.db.rollback(save_point=savepoint)
            execution_errors.append({
                "row_number": row["row_number"], "category": "Import Error",
                "reconciliation_key": row["reconciliation_key"], "message": cstr(exc),
            })

    return updated, updated_names, execution_errors


def process_import(file_url, requested_by):
    try:
        summary, classified, errors = _analyze(file_url)
        inserts = [item for item in classified if item["action"] == "insert"]
        updates = [item for item in classified if item["action"] == "update"]

        inserted = 0
        insert_failed = 0
        if inserts:
            savepoint = "pos_bank_import_insert_batch"
            frappe.db.savepoint(savepoint)
            try:
                inserted = _insert_rows(inserts, requested_by)
            except Exception as exc:
                frappe.db.rollback(save_point=savepoint)
                insert_failed = len(inserts)
                frappe.log_error(frappe.get_traceback(), "POS Bank Import - Insert")
                errors.append({"category": "Import Error", "message": _("Insert batch failed: {0}").format(cstr(exc))})

        updated, updated_names, update_errors = _update_rows(updates)
        errors.extend(update_errors)

        if updated_names:
            from marina_custom_apps.pos_reconciliation.accounting_service import sync_accounting_status_for_bank_transactions
            sync_accounting_status_for_bank_transactions(updated_names)

        summary["inserted_records"] = inserted
        summary["updated_records"] = updated
        # error_records counts affected rows, not just displayed error messages.
        summary["error_records"] = summary["error_records"] + len(update_errors) + insert_failed
        summary["skipped_records"] = (
            summary["unchanged_records"]
            + summary["conflict_records"]
            + summary["error_records"]
        )

        status = "Completed" if not (summary["error_records"] or summary["conflict_records"]) else "Completed with Errors"
        _save_summary(summary, status, errors, processed_by=requested_by)
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "POS Bank Import")
        failed = {
            "total_rows": 0, "new_records": 0, "update_records": 0, "unchanged_records": 0,
            "conflict_records": 0, "error_records": 1, "inserted_records": 0,
            "updated_records": 0, "skipped_records": 1, "date_conversions": 0,
        }
        _save_summary(
            failed, "Failed",
            [{"category": "System Error", "message": frappe.get_traceback()[-1500:]}],
            processed_by=requested_by,
        )
        frappe.db.commit()


def start_import(file_url=None):
    _check_permission()
    if cstr(frappe.db.get_single_value(TOOL_DOCTYPE, "status")) == "Importing":
        frappe.throw(_("A Bank import is already running."))

    summary, _classified, errors = _analyze(file_url)
    _save_summary(summary, "Importing", errors)

    requested_by = frappe.session.user
    frappe.enqueue(
        "marina_custom_apps.pos_reconciliation.bank_import_service.process_import",
        queue="long", timeout=3600,
        job_name=f"POS Bank Import {now_datetime()}",
        file_url=file_url, requested_by=requested_by,
        enqueue_after_commit=True,
    )
    return {"queued": 1, **summary}


def get_import_status():
    if not frappe.has_permission(TOOL_DOCTYPE, ptype="read"):
        frappe.throw(_("You do not have permission to view Bank Import status."), frappe.PermissionError)
    doc = frappe.get_single(TOOL_DOCTYPE)
    return {
        "status": doc.status, "total_rows": doc.total_rows,
        "inserted_records": doc.inserted_records, "updated_records": doc.updated_records,
        "unchanged_records": doc.unchanged_records, "skipped_records": doc.skipped_records,
        "error_records": doc.error_records, "conflict_records": doc.conflict_records,
    }


def clear_import_summary():
    _check_permission()
    if cstr(frappe.db.get_single_value(TOOL_DOCTYPE, "status")) == "Importing":
        frappe.throw(_("Cannot clear the summary while an import is running."))
    empty = {
        "total_rows": 0, "new_records": 0, "update_records": 0, "unchanged_records": 0,
        "conflict_records": 0, "error_records": 0, "inserted_records": 0,
        "updated_records": 0, "skipped_records": 0, "date_conversions": 0,
    }
    return _save_summary(empty, "Ready", [])


def _workspace_doc():
    if not frappe.db.exists("Workspace", WORKSPACE):
        return None
    return frappe.get_doc("Workspace", WORKSPACE)


def _set_workspace_visibility(enabled):
    workspace = _workspace_doc()
    if not workspace:
        return False

    changed = False
    enabled = cint(enabled)
    shortcut_rows = workspace.get("shortcuts") or []
    matching_shortcuts = [row for row in shortcut_rows if row.type == "DocType" and row.link_to == TOOL_DOCTYPE]
    if enabled and not matching_shortcuts:
        workspace.append("shortcuts", {
            "type": "DocType", "link_to": TOOL_DOCTYPE, "doc_view": "",
            "label": SHORTCUT_LABEL, "color": "Green",
        })
        changed = True
    elif not enabled and matching_shortcuts:
        for row in list(matching_shortcuts):
            shortcut_rows.remove(row)
        changed = True

    link_rows = workspace.get("links") or []
    matching_links = [
        row for row in link_rows
        if row.type == "Link" and row.link_type == "DocType" and row.link_to == TOOL_DOCTYPE
    ]
    if enabled and not matching_links:
        workspace.append("links", {
            "type": "Link", "label": SHORTCUT_LABEL, "link_type": "DocType",
            "link_to": TOOL_DOCTYPE, "is_query_report": 0, "onboard": 1, "hidden": 0,
        })
        changed = True
    elif not enabled and matching_links:
        for row in list(matching_links):
            link_rows.remove(row)
        changed = True

    try:
        content = json.loads(workspace.content or "[]")
    except (TypeError, ValueError):
        content = []
    if not isinstance(content, list):
        content = []

    blocks = [
        block for block in content
        if block.get("type") == "shortcut"
        and block.get("data", {}).get("shortcut_name") == SHORTCUT_LABEL
    ]
    if enabled and not blocks:
        insert_at = 1 if content and content[0].get("type") == "header" else 0
        content.insert(insert_at, {
            "id": "pr-bank-import-v05210", "type": "shortcut",
            "data": {"shortcut_name": SHORTCUT_LABEL, "col": 3},
        })
        workspace.content = json.dumps(content, separators=(",", ":"))
        changed = True
    elif not enabled and blocks:
        workspace.content = json.dumps([block for block in content if block not in blocks], separators=(",", ":"))
        changed = True

    if changed:
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)
        frappe.clear_cache()
    return changed


def set_tool_enabled(enabled=1):
    enabled = cint(enabled)
    frappe.db.set_single_value(TOOL_DOCTYPE, "tool_enabled", enabled)
    _set_workspace_visibility(enabled)
    return {"enabled": enabled}


def install_tool():
    frappe.db.set_single_value(TOOL_DOCTYPE, "tool_enabled", 1)
    if not frappe.db.get_single_value(TOOL_DOCTYPE, "status"):
        frappe.db.set_single_value(TOOL_DOCTYPE, "status", "Ready")
    _set_workspace_visibility(1)
