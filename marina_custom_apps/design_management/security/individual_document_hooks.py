"""Individual policy gates for Design DocTypes without specialized scope hooks.

Unconfigured users retain native Frappe permissions; a configured profile
can deny any operation but cannot elevate native Frappe DocPerm grants.
"""
from marina_custom_apps.design_management.security.user_permissions import document_allowed


def _operation(ptype):
    return "read" if ptype in (None, "select", "print", "export") else ptype


def _check(doc, ptype=None, user=None):
    return document_allowed(doc.doctype, _operation(ptype), user)


def _query(doctype, user=None):
    allowed = document_allowed(doctype, "read", user)
    return "1=0" if allowed is False else ""


def design_milestone_type_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_milestone_type_query(user=None):
    return _query("Design Milestone Type", user)


def design_milestone_plan_entry_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_milestone_plan_entry_query(user=None):
    return _query("Design Milestone Plan Entry", user)


def design_milestone_execution_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_milestone_execution_query(user=None):
    return _query("Design Milestone Execution", user)


def design_milestone_custody_event_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_milestone_custody_event_query(user=None):
    return _query("Design Milestone Custody Event", user)


def design_document_type_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_document_type_query(user=None):
    return _query("Design Document Type", user)


def design_item_creation_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def design_item_creation_query(user=None):
    return _query("Design Item Creation", user)


def marina_pantone_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def marina_pantone_query(user=None):
    return _query("Marina Pantone", user)


def marina_fashion_category_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def marina_fashion_category_query(user=None):
    return _query("Marina Fashion Category", user)


def factory_list_permission(doc, ptype=None, user=None, **kwargs):
    return _check(doc, ptype, user)


def factory_list_query(user=None):
    return _query("Factory List", user)


