"""Non-destructive conversion of existing Category and Subcategory records to nested set."""
import frappe

def migrate_category_tree():
    dt = "Marina Fashion Category"
    if not frappe.db.exists("DocType", dt):
        return
    if not all(frappe.db.has_column(dt, col) for col in ("lft", "rgt", "is_group", "old_parent")):
        return
    rows = frappe.get_all(dt, fields=["name", "parent_category", "is_group", "lft", "rgt"])
    if not rows:
        return
    parents = {row.name for row in rows if not row.parent_category}
    for row in rows:
        if row.parent_category and row.parent_category not in parents:
            frappe.throw("Fashion Category migration blocked: invalid or third-level parent on " + row.name)
    if all(row.lft and row.rgt and bool(row.is_group) == (not bool(row.parent_category)) for row in rows):
        return
    for row in rows:
        frappe.db.set_value(dt, row.name, {
            "is_group": 0 if row.parent_category else 1,
            "old_parent": row.parent_category,
        }, update_modified=False)
    from frappe.utils.nestedset import rebuild_tree
    rebuild_tree(dt)
