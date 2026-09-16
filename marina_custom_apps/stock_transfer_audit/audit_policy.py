from datetime import date, datetime, timedelta


DEFAULT_AUDIT_PROCESS_START_DATE = date(2026, 9, 16)


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value))
    return None


def effective_audit_window(from_date, to_date, process_start_date):
    requested_from = as_date(from_date)
    requested_to = as_date(to_date)
    process_start = as_date(process_start_date) or DEFAULT_AUDIT_PROCESS_START_DATE

    if not requested_from or not requested_to:
        raise ValueError("From Date and To Date are required.")
    if requested_from > requested_to:
        raise ValueError("From Date cannot be after To Date.")

    effective_from = max(requested_from, process_start)
    has_eligible_window = effective_from <= requested_to
    legacy_to = min(requested_to, process_start - timedelta(days=1))
    has_legacy_window = requested_from <= legacy_to

    return {
        "requested_from": requested_from,
        "requested_to": requested_to,
        "process_start": process_start,
        "effective_from": effective_from if has_eligible_window else None,
        "effective_to": requested_to if has_eligible_window else None,
        "legacy_from": requested_from if has_legacy_window else None,
        "legacy_to": legacy_to if has_legacy_window else None,
    }


def controlled_receive_issue(created_via_end_transit, receiving_method):
    if not created_via_end_transit:
        return "not created through End Transit"
    if not (receiving_method or "").strip():
        return "Receiving Method is missing"
    return None


def start_date_change_issue(previous, current, audit_records_exist):
    previous_date = as_date(previous)
    current_date = as_date(current)
    if (
        audit_records_exist
        and previous_date
        and current_date
        and current_date < previous_date
    ):
        return (
            "Audit Process Start Date cannot be moved backwards after "
            "Stock Transfer Audit Records have been created."
        )
    return None
