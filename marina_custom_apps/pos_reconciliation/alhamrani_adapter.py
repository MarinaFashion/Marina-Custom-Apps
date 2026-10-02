from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cstr, flt, get_datetime, getdate

from marina_custom_apps.pos_reconciliation.doctype.bank_pos_transaction.bank_pos_transaction import (
    build_reconciliation_key,
    normalize_transaction_type,
)

ALHAMRANI_DOCTYPE = "Alhamrani Transaction"

FIELD_CANDIDATES = {
    "status": ("status",),
    "terminal_id": ("tid", "terminal_id", "device_terminal_id"),
    "rrn": ("rrn", "reference_number"),
    "auth_code": ("auth_code", "authorization_code"),
    "transaction_type": ("message_id", "transaction_type", "txn_type"),
    "amount": ("amount_echoed", "amount", "amount_sent"),
    "card_type": ("card_type",),
    "masked_pan": ("masked_pan", "masked_card_number"),
    "pos_profile": ("pos_profile",),
    "response_code": ("response_code",),
    "sent_at": ("sent_at",),
    "responded_at": ("responded_at",),
    "request_json": ("request_json",),
    "response_json": ("response_json",),
}

JSON_KEY_CANDIDATES = {
    "terminal_id": ("tid", "terminalid", "terminal_id"),
    "rrn": ("rrn", "retrievalreferencenumber", "reference_number"),
    "auth_code": ("authcode", "auth_code", "authorizationcode"),
    "transaction_type": ("transactiontype", "transaction_type", "txntype", "messageid", "message_id"),
    "card_type": ("cardtype", "card_type"),
    "masked_pan": ("maskedpan", "masked_pan", "maskedcardnumber"),
    "transaction_date": ("transactiondate", "transaction_date", "txndate", "txn_date"),
    "transaction_time": ("transactiontime", "transaction_time", "txntime", "txn_time"),
}


def _norm_key(value):
    return "".join(ch for ch in cstr(value).lower() if ch.isalnum() or ch == "_")


def _walk_json(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield _norm_key(key), item
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _parse_json(value):
    if isinstance(value, (dict, list)):
        return value
    text = cstr(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _json_value(payloads, candidates):
    wanted = {_norm_key(candidate) for candidate in candidates}
    for payload in payloads:
        parsed = _parse_json(payload)
        if parsed is None:
            continue
        for key, value in _walk_json(parsed):
            if key in wanted and value not in (None, ""):
                return value
    return None


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, (datetime,)):
        return getdate(value)
    text = cstr(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    try:
        return getdate(text)
    except Exception:
        return None


def _parse_time(value):
    if not value:
        return None
    if hasattr(value, "strftime") and not isinstance(value, str):
        try:
            return value.strftime("%H:%M:%S")
        except Exception:
            pass
    text = cstr(value).strip().split(".", 1)[0]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M:%S")
        except ValueError:
            pass
    return text or None


class AlhamraniAdapter:
    def __init__(self):
        if not frappe.db.exists("DocType", ALHAMRANI_DOCTYPE):
            frappe.throw(_("Alhamrani Transaction DocType is not installed on this site."))

        self.meta = frappe.get_meta(ALHAMRANI_DOCTYPE)
        self.fields = {
            logical: self._first_existing(candidates)
            for logical, candidates in FIELD_CANDIDATES.items()
        }
        self._validate_required_fields()

    def _first_existing(self, candidates):
        for fieldname in candidates:
            if self.meta.has_field(fieldname):
                return fieldname
        return None

    def _validate_required_fields(self):
        missing = []
        for logical in ("terminal_id", "rrn", "auth_code"):
            if not self.fields.get(logical):
                missing.append(logical)
        if not self.fields.get("transaction_type") and not (
            self.fields.get("request_json") or self.fields.get("response_json")
        ):
            missing.append("transaction_type")
        if not self.fields.get("amount"):
            missing.append("amount")
        if not self.fields.get("status") and not self.fields.get("response_code"):
            missing.append("status/response_code")

        if missing:
            frappe.throw(
                _("Alhamrani Transaction is missing required reconciliation fields: {0}").format(
                    ", ".join(missing)
                )
            )

    def query_fields(self):
        fields = ["name", "creation"]
        for fieldname in self.fields.values():
            if fieldname and fieldname not in fields:
                fields.append(fieldname)
        return fields

    def preferred_datetime_field(self):
        return self.fields.get("responded_at") or self.fields.get("sent_at") or "creation"

    def get_rows(self, from_date, to_date):
        # One-day buffer protects terminal-response timestamps around midnight;
        # final filtering is done using the normalized transaction date.
        start = f"{add_days(getdate(from_date), -1)} 00:00:00"
        end = f"{add_days(getdate(to_date), 1)} 23:59:59"
        dt_field = self.preferred_datetime_field()
        filters = {dt_field: ["between", [start, end]]}
        return frappe.get_all(
            ALHAMRANI_DOCTYPE,
            filters=filters,
            fields=self.query_fields(),
            order_by=f"{dt_field} asc",
            limit_page_length=0,
        )

    def _value(self, row, logical):
        fieldname = self.fields.get(logical)
        if fieldname:
            value = row.get(fieldname)
            if value not in (None, ""):
                return value

        payloads = [
            row.get(self.fields.get("response_json")) if self.fields.get("response_json") else None,
            row.get(self.fields.get("request_json")) if self.fields.get("request_json") else None,
        ]
        candidates = JSON_KEY_CANDIDATES.get(logical)
        if candidates:
            return _json_value(payloads, candidates)
        return None

    def is_approved(self, row):
        status = cstr(self._value(row, "status")).strip().upper()
        response_code = cstr(self._value(row, "response_code")).strip().upper()
        if status:
            return status in {"APPROVED", "SUCCESS", "COMPLETED"}
        return response_code in {"00", "000"}

    def normalized_row(self, row):
        payloads = [
            row.get(self.fields.get("response_json")) if self.fields.get("response_json") else None,
            row.get(self.fields.get("request_json")) if self.fields.get("request_json") else None,
        ]

        terminal_id = cstr(self._value(row, "terminal_id")).strip()
        rrn = cstr(self._value(row, "rrn")).strip()
        auth_code = cstr(self._value(row, "auth_code")).strip()

        transaction_type = normalize_transaction_type(self._value(row, "transaction_type"))
        if transaction_type not in {"PURCHASE", "REFUND"}:
            json_transaction_type = _json_value(payloads, JSON_KEY_CANDIDATES["transaction_type"])
            if json_transaction_type:
                transaction_type = normalize_transaction_type(json_transaction_type)

        amount_raw = self._value(row, "amount")

        response_tx_date = _parse_date(_json_value(payloads, JSON_KEY_CANDIDATES["transaction_date"]))
        response_tx_time = _parse_time(_json_value(payloads, JSON_KEY_CANDIDATES["transaction_time"]))
        tx_date = response_tx_date
        tx_time = response_tx_time

        fallback_dt = None
        for logical in ("responded_at", "sent_at"):
            fieldname = self.fields.get(logical)
            if fieldname and row.get(fieldname):
                fallback_dt = get_datetime(row.get(fieldname))
                break
        if fallback_dt is None and row.get("creation"):
            fallback_dt = get_datetime(row.creation)

        if not tx_date and fallback_dt:
            tx_date = fallback_dt.date()
        if not tx_time and fallback_dt:
            tx_time = fallback_dt.strftime("%H:%M:%S")

        key = None
        key_error = None
        try:
            key = build_reconciliation_key(terminal_id, rrn, auth_code, transaction_type)
        except Exception:
            key_error = _("Incomplete reconciliation key")

        return frappe._dict(
            name=row.name,
            terminal_id=terminal_id,
            rrn=rrn,
            auth_code=auth_code,
            transaction_type=transaction_type,
            amount=flt(amount_raw, 2) if amount_raw not in (None, "") else None,
            card_type=cstr(self._value(row, "card_type")).strip(),
            masked_pan=cstr(self._value(row, "masked_pan")).strip(),
            transaction_date=tx_date,
            transaction_time=tx_time,
            comparison_transaction_date=response_tx_date,
            comparison_transaction_time=response_tx_time,
            source_pos_profile=cstr(self._value(row, "pos_profile")).strip(),
            status=cstr(self._value(row, "status")).strip(),
            response_code=cstr(self._value(row, "response_code")).strip(),
            reconciliation_key=key,
            key_error=key_error,
        )
