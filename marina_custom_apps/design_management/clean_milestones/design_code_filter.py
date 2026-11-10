"""Validate exact Design Code lists before an indexed Follow-Up Grid query.

No database work here; caller intersects these IDs with ordinary permissions
and any optional custody/other filters before pagination.
"""
import json

MAX_CODES = 500


def parse_design_codes(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid multiple Design Codes selection") from exc
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CODES:
        raise ValueError("Select between 1 and 500 Design Codes")
    codes = []
    seen = set()
    for code in value:
        if (not isinstance(code, str) or not 0 < len(code) <= 140
                or code != code.strip() or any(c.isspace() for c in code)):
            raise ValueError("Each Design Code must be a valid nonempty code (up to 140 characters)")
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def restrict_to_design_codes(filters, codes):
    """Intersect existing name restriction (custody) with exact pasted IDs."""
    if not codes:
        return True
    existing = filters.get("name")
    if existing is not None:
        if (not isinstance(existing, list) or len(existing) != 2
                or existing[0] != "in"):
            raise ValueError("Unsupported Design Code restriction")
        permitted = set(existing[1])
        codes = [code for code in codes if code in permitted]
    if not codes:
        return False
    filters["name"] = ["in", codes]
    return True
