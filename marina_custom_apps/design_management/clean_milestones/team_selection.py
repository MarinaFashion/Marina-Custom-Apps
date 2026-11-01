"""Pure Design Team pool selection.

A Mood Board may contain several employees with the same module role.
A Design Code keeps one responsible employee per role for unambiguous custody.
"""
from collections import defaultdict


def value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def active_pools(rows):
    """Validate distinct (role, user) pairs and at most one default per role."""
    pools = defaultdict(list)
    pairs = set()
    for row in rows or []:
        if not value(row, "active"):
            continue
        role, user = value(row, "module_role"), value(row, "user")
        if not role or not user or (role, user) in pairs:
            raise ValueError("Choose a valid, unique employee for each Role + User pair")
        pairs.add((role, user))
        pools[role].append(row)
    for role, members in pools.items():
        marked = [r for r in members if value(r, "default_for_design", 0)]
        if len(marked) > 1:
            raise ValueError("Select no more than one Default for New Designs for role " + role)
    return pools


def choose_design_assignments(rows, preferred_users=None):
    """One user per role. Never choose arbitrarily from multiple candidates.

    Explicit Design owner selection wins if that user belongs to the pool;
    otherwise the marked Default wins. A single member is unambiguous.
    Roles with multiple staff but no selection are left for manager assignment.
    """
    pools = active_pools(rows)
    preferred_users = preferred_users or {}
    chosen = {}
    for role, members in pools.items():
        preferred = preferred_users.get(role)
        if preferred:
            match = next((r for r in members if value(r, "user") == preferred), None)
            if match:
                chosen[role] = value(match, "user")
                continue
        marked = next((r for r in members if value(r, "default_for_design", 0)), None)
        if marked:
            chosen[role] = value(marked, "user")
        elif len(members) == 1:
            chosen[role] = value(members[0], "user")
    return chosen
