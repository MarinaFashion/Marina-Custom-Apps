"""Pure Release 22 rules for controlled return to an earlier milestone.

Display sequence is the rollback frontier (not the workflow activation lock).
Existing milestone execution IDs and history remain owned by their plan entry.
"""

def later_plans(plans, target):
    """Later display rows PLUS transitive dependents, including parallel work.

    A customized master may put a dependent before its predecessor in the
    display sequence. It still must return to Future with that predecessor.
    """
    key = (int(target["sequence"] or 0), target["milestone_type"])
    selected = {
        p["milestone_type"] for p in plans
        if (int(p["sequence"] or 0), p["milestone_type"]) > key
    }
    selected.add(target["milestone_type"])
    while True:
        newly = {
            p["milestone_type"] for p in plans
            if p.get("depends_on_type") in selected
        } - selected
        if not newly:
            break
        selected.update(newly)
    selected.discard(target["milestone_type"])
    return sorted(
        [p for p in plans if p["milestone_type"] in selected],
        key=lambda p: (int(p["sequence"] or 0), p["milestone_type"]),
    )


def trigger_reached(configured, required, current):
    """Catch up an earlier trigger when resuming after a controlled rollback.

    The ordinary event match still works. A later NORMAL step also counts as
    having reached the earlier trigger, so a return to Bulk Production /
    In Progress will not strand the parallel Final QC when Bulk completes.
    Rework never counts as having passed a normal trigger.
    """
    if current == required:
        return True
    normal = [row["step"] for row in configured if row["step"] != "Rework"]
    return (required in normal and current in normal
            and normal.index(current) > normal.index(required))
