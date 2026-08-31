import frappe

def _is_manager(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "Stock Manager" in frappe.get_roles(user)

def store_cycle_count_query(user=None):
    user = user or frappe.session.user
    if _is_manager(user):
        return ""
    return f"`tabStore Cycle Count`.`assigned_to` = {frappe.db.escape(user)}"

def store_cycle_count_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    return _is_manager(user) or doc.assigned_to == user
