"""Pure, auditable published Design Document assignment comparison.

Adding a new style is permitted; changing or removing an existing published
assignment requires the separate controlled procedures, never a normal Save.
"""
def _items(rows):
    return {row.get("design_code"): row.get("target_milestone_type") or None
            for row in rows if row.get("design_code")}

def assignment_delta(previous, current):
    old, new = _items(previous), _items(current)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    remapped = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return added, removed, remapped

def default_assignment_milestone(value, document_milestone, *, existing=False):
    """Copy the document milestone only for new assignments without an override.

    A blank historical row means 'inherit from the parent' and must remain
    untouched, especially on a Published document: materializing it later
    would falsely appear as a protected assignment remap.
    """
    if existing:
        return value
    return value or document_milestone or None
