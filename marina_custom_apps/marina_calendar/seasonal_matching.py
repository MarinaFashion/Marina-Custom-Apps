"""Seasonal analog weights; no date conversion or database access."""
import math

HIJRI_MONTHS = {8, 9, 11, 12}


def matching_basis(month, override=None):
    if override in ("Hijri", "Gregorian"):
        return override
    return "Hijri" if int(month or 0) in HIJRI_MONTHS else "Gregorian"


def seasonal_weight(basis, target_month, target_day, historical_month, historical_day):
    """Reward only the chosen calendar, retaining other analog dimensions."""
    if not target_month or int(historical_month or 0) != int(target_month):
        return 1.0
    weight = 1.8
    if target_day and historical_day:
        distance = abs(int(target_day) - int(historical_day))
        weight *= 1 + math.exp(-distance / 5.0)
    return weight
