"""Seasonal analog weights; no date conversion or database access."""
import math

def matching_basis(month, override=None):
    """Return the calendar basis selected explicitly on the calendar date."""
    if override in ("Hijri", "Gregorian"):
        return override
    return None


def seasonal_weight(basis, target_month, target_day, historical_month, historical_day):
    """Reward only the chosen calendar, retaining other analog dimensions."""
    if not target_month or int(historical_month or 0) != int(target_month):
        return 1.0
    weight = 1.8
    if target_day and historical_day:
        distance = abs(int(target_day) - int(historical_day))
        if basis == "Hijri":
            # Preserve the shape within the lunar month: exact and nearby
            # Hijri days must dominate distant days in the same month.
            weight *= 1 + 5 * math.exp(-distance / 3.0)
        else:
            weight *= 1 + math.exp(-distance / 5.0)
    return weight


def hijri_month_rows(rows, month):
    """Return usable observations from one Hijri month."""
    target_month = int(month or 0)
    if not target_month:
        return []

    def value(row, field):
        return row.get(field) if isinstance(row, dict) else getattr(row, field, None)

    return [
        row for row in rows
        if int(value(row, "hijri_month") or 0) == target_month
        and 1 <= int(value(row, "hijri_day") or 0) <= 30
    ]
