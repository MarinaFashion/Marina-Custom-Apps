"""Exact monthly precision management; pure functions, no database writes.

The monthly earning is stored as a six-decimal decimal string in the journal.
The HRMS adjustment uses three decimals. Residual is carried forward only
from successfully posted entries; never from unposted previews.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib

SIX = Decimal("0.000001")
THREE = Decimal("0.001")


def as_six(value):
    return Decimal(str(value)).quantize(SIX, rounding=ROUND_HALF_UP)


def calculate_posting(exact_credit, prior_residual="0"):
    credit = as_six(exact_credit)
    opening = as_six(prior_residual)
    if credit < 0:
        raise ValueError("Monthly credit cannot be negative")
    if abs(opening) >= THREE:
        raise ValueError("Residual outside permitted three-decimal range")
    amount = (credit + opening).quantize(THREE, rounding=ROUND_HALF_UP)
    closing = (credit + opening - amount).quantize(SIX, rounding=ROUND_HALF_UP)
    return {
        "exact_credit": f"{credit:.6f}",
        "opening_residual": f"{opening:.6f}",
        "hrms_credit": f"{amount:.3f}",
        "closing_residual": f"{closing:.6f}",
    }


def posting_key(company, employee, leave_type, credit_date):
    day = credit_date if isinstance(credit_date, date) else date.fromisoformat(str(credit_date)[:10])
    if day.day < 28:
        raise ValueError("Expected month-end credit date")
    raw = "|".join((company, employee, leave_type, day.isoformat()))
    return "MLPJ-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32].upper()
