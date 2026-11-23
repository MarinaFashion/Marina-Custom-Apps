"""Pure accrual calculator for Marina annual paid leave.

PHASE 1 / SIMULATION ONLY. Assumptions are deliberately explicit:
* 30-day contract: 30 / 330 eligible standardized days
* 21-day contract: 21 / 339 eligible standardized days
* Every full calendar month represents 30 service units. Partial months and
  excluded absences are normalized by actual days in that calendar month.
* Accrual for a completed month is credited on its final calendar day.
* Contract-year cap is 21 or 30; year boundaries are joining anniversaries.
These conventions must be approved by HR before live posting. No writes here.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

D = Decimal
RATES = {"Annual 21": (D("21"), D("339")), "Annual 30": (D("30"), D("330"))}


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def month_next(day):
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def anniversary(joining, year):
    # Explicit Feb 29 rule: use Feb 28 in non-leap years.
    return date(year, joining.month, min(joining.day, calendar.monthrange(year, joining.month)[1]))


def contract_start(joining, day):
    year = day.year
    candidate = anniversary(joining, year)
    if candidate > day:
        year -= 1
    return anniversary(joining, year)


def quantize(value):
    return str(value.quantize(D("0.000001"), rounding=ROUND_HALF_UP))


def simulate(joining_date, entitlement, through_date, leave_intervals=()):
    """Return monthly posted credit simulation (never writes to DB).

    leave_intervals: iterable of {from_date, to_date, fraction?}, where
    fraction=1 for full-day absence and 0.5 for a single half-day.
    Overlaps are combined by daily maximum, not added twice.
    """
    if entitlement not in RATES:
        raise ValueError("Unsupported entitlement: " + str(entitlement))
    joining, through = _date(joining_date), _date(through_date)
    if through < joining:
        return {"rows": [], "earned": "0.000000", "excluded_days": "0.000000",
                "unposted_month": None, "assumptions": "simulation only"}
    annual, divisor = RATES[entitlement]
    absences = {}
    for interval in leave_intervals:
        start, end = _date(interval["from_date"]), _date(interval["to_date"])
        fraction = D(str(interval.get("fraction", 1)))
        if not D("0") <= fraction <= D("1"):
            raise ValueError("Absence fraction must be between 0 and 1")
        if end < start:
            raise ValueError("Absence to_date precedes from_date")
        day = max(start, joining)
        end = min(end, through)
        while day <= end:
            absences[day] = max(absences.get(day, D("0")), fraction)
            day += timedelta(days=1)

    year_credits = {}
    rows = []
    earned = D("0")
    excluded = D("0")
    cursor = date(joining.year, joining.month, 1)
    while cursor <= through:
        next_month = month_next(cursor)
        end = min(next_month - timedelta(days=1), through)
        # Credit only fully completed calendar months, on their final day.
        if next_month - timedelta(days=1) > through:
            break
        month_days = D(calendar.monthrange(cursor.year, cursor.month)[1])
        month_credit = D("0")
        month_excluded = D("0")
        day = max(joining, cursor)
        while day <= end:
            fraction = absences.get(day, D("0"))
            month_excluded += fraction
            standardized_service = (D("1") - fraction) * D("30") / month_days
            if standardized_service:
                cycle = contract_start(joining, day)
                already = year_credits.get(cycle, D("0"))
                credit = min(standardized_service * annual / divisor,
                             max(D("0"), annual - already))
                year_credits[cycle] = already + credit
                month_credit += credit
            day += timedelta(days=1)
        earned += month_credit
        excluded += month_excluded
        rows.append({
            "month": cursor.isoformat(),
            "credit_date": (next_month - timedelta(days=1)).isoformat(),
            "earned": quantize(month_credit),
            "excluded_calendar_days": quantize(month_excluded),
            "cumulative_earned": quantize(earned),
        })
        cursor = next_month
    return {
        "rows": rows, "earned": quantize(earned),
        "excluded_days": quantize(excluded),
        "unposted_month": cursor.isoformat() if cursor <= through else None,
        "assumptions": "30/330 or 21/339 standardized units, credited month-end; provisional",
    }
