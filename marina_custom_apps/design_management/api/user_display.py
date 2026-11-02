"""Scoped user display names for Marina Design Management screens.

Do not alter ERPNext User IDs, Link field schema or global name formatting.
Return the User.username values for staff linked to an authorized Design Code.
"""
import frappe

MAX_DESIGN_USERS = 250


def usernames_for_user_ids(users, max_users=300):
    """One bounded lookup for permitted module records; never use full_name.

    Callers establish document/record access BEFORE invoking this helper.
    IDs remain unchanged in all links and audit data.
    """
    ids = sorted({u for u in (users or []) if isinstance(u, str) and u})
    if len(ids) > max_users:
        frappe.throw("Too many user references in this document")
    if not ids:
        return {}
    rows = frappe.get_all(
        "User", filters={"name": ["in", ids]},
        fields=["name", "username"], limit_page_length=len(ids))
    return {row.name: (row.username or "").strip() or "Username not configured"
            for row in rows}

@frappe.whitelist()
def design_code_list_merchandiser_usernames(design_codes):
    """User.username for visible Design Codes, in two bounded queries.

    Never accept arbitrary User IDs: independently verify which Design Codes
    the caller may read, then resolve only those designs' merchandisers.
    Return keyed by Design Code so no other user IDs leak to List View.
    """
    if isinstance(design_codes, str):
        design_codes = frappe.parse_json(design_codes)
    if not isinstance(design_codes, list) or len(design_codes) > 500:
        frappe.throw("Invalid Design Code list")
    if any(not isinstance(n, str) or not n or len(n) > 140
           for n in design_codes):
        frappe.throw("Invalid Design Code name")
    names = sorted(set(design_codes))
    if not names:
        return {}
    rows = frappe.get_list(
        "Design Code",
        filters={"name": ["in", names]},
        fields=["name", "assigned_merchandiser"],
        limit_page_length=len(names),
    )
    titles = usernames_for_user_ids(
        (row.assigned_merchandiser for row in rows if row.assigned_merchandiser),
        max_users=500,
    )
    return {
        row.name: titles.get(row.assigned_merchandiser,
                             "Username not configured")
        for row in rows if row.assigned_merchandiser
    }


@frappe.whitelist()
def design_code_user_names(design_code):
    """One bounded User query; no arbitrary-user enumeration endpoint."""
    doc = frappe.get_doc("Design Code", design_code)
    doc.check_permission("read")

    users = {u for u in (doc.assigned_merchandiser, doc.designer,
                         doc.get("technical_fitting_responsible")) if u}
    users.update(row.user for row in (doc.get("r22_team_assignments") or [])
                 if row.active and row.user)
    if len(users) > MAX_DESIGN_USERS:
        frappe.throw("Too many linked Design Code users")

    if not users:
        return {}
    return usernames_for_user_ids(users, max_users=MAX_DESIGN_USERS)


# A bounded, permission-scoped title lookup for user links in all module forms.
FORM_DOCTYPES = frozenset({
    "Design Code", "Mood Board", "Design Document", "Design Milestone Execution",
    "Design Management Settings", "Design Module Role", "Design Milestone Type",
    "Design Item Creation", "Production Colorway",
    "Design Document Type", "Design Module Managed Grant",
    "Design Milestone Plan Entry", "Design Milestone Custody Event",
    "Design Document Assignment Removal Log",
    "Marina Pantone", "Marina Fashion Category",
})


@frappe.whitelist()
def document_usernames(doctype, document_name):
    if doctype not in FORM_DOCTYPES:
        frappe.throw("Document is outside Marina Design Management", frappe.PermissionError)
    doc = frappe.get_doc(doctype, document_name)
    doc.check_permission("read")
    users = set()
    meta = frappe.get_meta(doctype)
    for field in meta.fields:
        value = doc.get(field.fieldname)
        if field.fieldtype == "Link" and field.options == "User" and value:
            users.add(value)
        elif field.fieldtype == "Table" and value:
            child = frappe.get_meta(field.options)
            user_fields = [f.fieldname for f in child.fields
                           if f.fieldtype == "Link" and f.options == "User"]
            for row in value[:300]:
                users.update(row.get(name) for name in user_fields if row.get(name))
    users.discard(None)
    if len(users) > 300:
        frappe.throw("Too many user references in this document")
    if not users:
        return {}
    return usernames_for_user_ids(users)
