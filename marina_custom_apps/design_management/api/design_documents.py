"""Permission-scoped endpoints for static Design Document assignments."""
import frappe
from marina_custom_apps.design_management.security.document_access import can_manage_documents


@frappe.whitelist()
def preview_design_codes(filters=None, limit=100):
    if not can_manage_documents(frappe.session.user):
        frappe.throw("Not authorized to assign documents", frappe.PermissionError)
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    filters = filters or {}
    if not isinstance(filters, dict):
        frappe.throw("Invalid filter object")
    allowed = {"mood_board", "category", "subcategory", "year", "season",
               "collection", "assigned_merchandiser", "design_number"}
    query = {k: v for k, v in filters.items() if k in allowed and isinstance(v, str) and v}
    limit = min(max(int(limit), 1), 200)
    matches = frappe.get_list("Design Code", filters=query,
        fields=["name", "mood_board", "category", "subcategory", "assigned_merchandiser"],
        limit_page_length=limit, order_by="name asc")
    from marina_custom_apps.design_management.api.user_display import usernames_for_user_ids
    titles = usernames_for_user_ids(
        (row.assigned_merchandiser for row in matches if row.assigned_merchandiser),
        max_users=limit)
    return [
        dict(row, assigned_merchandiser_username=(
            titles.get(row.assigned_merchandiser, "Username not configured")
            if row.assigned_merchandiser else ""))
        for row in matches
    ]


@frappe.whitelist()
def related_documents(design_code):
    if not frappe.has_permission("Design Code", "read", doc=design_code):
        frappe.throw("Not authorized to view Design Code", frappe.PermissionError)
    links = frappe.get_all("Design Document Assignment",
        filters={"design_code": design_code, "parenttype": "Design Document", "parentfield": "assignments"},
        fields=["parent", "assigned_by", "assigned_on", "target_milestone_type"],
        limit_page_length=501)
    if len(links) > 500:
        frappe.throw("Too many Design Document links")
    if not links:
        return []
    # Respect Frappe record permissions when returning file links and
    # document metadata (child assignments alone do not grant file access).
    docs = frappe.get_list("Design Document",
        filters={"name": ["in", sorted({r.parent for r in links})]},
        fields=["name", "document_title", "document_type", "attachment",
                "publication_status", "related_milestone_type",
                "added_by", "added_on"],
        limit_page_length=500)
    by_id = {r.name: r for r in docs}
    user_ids = sorted({r.added_by for r in docs if r.added_by})
    titles = {r.name: ((r.username or "").strip() or "Username not configured")
              for r in frappe.get_all("User",
                  filters={"name": ["in", user_ids]}, fields=["name", "username"],
                  limit_page_length=len(user_ids))} if user_ids else {}
    return [dict(by_id[row.parent], added_username=titles.get(
                by_id[row.parent].added_by, "Username not configured"),
                assigned_on=row.assigned_on,
                target_milestone_type=(row.target_milestone_type or
                                       by_id[row.parent].related_milestone_type))
            for row in links if row.parent in by_id]


@frappe.whitelist()
def search_eligible_users(doctype, txt, searchfield, start, page_len, filters):
    if not (frappe.has_permission("Design Code", "read")
            or frappe.has_permission("Mood Board", "read")
            or frappe.has_permission("Design Document", "read")):
        return []
    team = (filters or {}).get("team")
    if team not in ("designers", "merchandisers"):
        return []
    from marina_custom_apps.design_management.security.document_access import configured_users
    users = sorted(configured_users(team))
    if not users:
        return []

    # User.name is the stable email/ID, but employees search by Username.
    # Resolve a maximum of 1000 configured employees in ONE indexed User
    # lookup, instead of performing a User query for each link suggestion.
    records = frappe.get_all(
        "User",
        filters={"name": ["in", users], "enabled": 1,
                 "user_type": "System User"},
        fields=["name", "username"],
        limit_page_length=len(users),
    )
    needle = (txt or "").strip().casefold()
    matched = [
        (row.name, (row.username or "").strip())
        for row in records
        if row.username and (needle in row.name.casefold()
        or needle in row.username.casefold())
    ]
    matched.sort(key=lambda pair: (pair[1].casefold(), pair[0].casefold()))
    page_start = max(int(start), 0)
    return matched[page_start:page_start + min(max(int(page_len), 1), 50)]


def _may_remove_published_assignment(document):
    from marina_custom_apps.design_management.security.role_access import enabled, can_action
    from marina_custom_apps.design_management.security.permissions import is_manager
    user = frappe.session.user
    if not frappe.has_permission("Design Document", "write", doc=document, user=user):
        return False
    if not can_manage_documents(user):
        return False
    from marina_custom_apps.design_management.security.user_permissions import configured
    if enabled() or configured(user):
        return can_action("Remove Published Assignment", user)
    return is_manager(user) and (
        user == "Administrator" or "System Manager" in frappe.get_roles(user)
    )


@frappe.whitelist()
def can_remove_published_assignment(document_name):
    document = frappe.get_doc("Design Document", document_name)
    return bool(document.publication_status == "Published" and
                document.get("assignments") and
                _may_remove_published_assignment(document))


@frappe.whitelist(methods=["POST"])
def remove_published_assignment(document_name, design_code, reason):
    """Unlink a Design only; the immutable published file is not changed.

    Refuses any link that currently serves as milestone evidence. Saved and
    audited in one transaction; failed authorization rolls back everything.
    """
    reason = (reason or "").strip()
    if len(reason) < 10 or len(reason) > 500:
        frappe.throw("Provide an assignment removal reason (10–500 characters)")
    from marina_custom_apps.design_management.clean_milestones.service import _lock_design
    _lock_design(design_code)
    frappe.db.sql(
        "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
        (document_name,))
    document = frappe.get_doc("Design Document", document_name, for_update=True)
    if document.publication_status != "Published":
        frappe.throw("This action is only for published document assignments")
    if not _may_remove_published_assignment(document):
        frappe.throw("Not authorized to detach this published document", frappe.PermissionError)
    matches = [row for row in (document.get("assignments") or [])
               if row.design_code == design_code]
    if len(matches) != 1:
        frappe.throw("Design Code is not assigned to this document")
    if (frappe.db.exists("Design Milestone Execution",
            {"design_code": design_code, "evidence_document": document.name})
            or frappe.db.exists("Design Milestone Custody Event",
            {"design_code": design_code, "evidence_document": document.name})):
        frappe.throw("Cannot detach a document used as current or historical milestone evidence")
    document.set("assignments", [
        row for row in (document.get("assignments") or [])
        if row.design_code != design_code
    ])
    frappe.flags.marina_published_detach_doc = document.name
    try:
        document.save()
    finally:
        frappe.flags.marina_published_detach_doc = None
    from frappe.utils import now_datetime
    frappe.get_doc({
        "doctype": "Design Document Assignment Removal Log",
        "document_ref": document_name,
        "design_code_ref": design_code,
        "publication_status": "Published",
        "removed_by": frappe.session.user,
        "removed_on": now_datetime(),
        "reason": reason
    }).insert(ignore_permissions=True)
    return {"removed": design_code, "document": document_name}


# Link Published documents from Design Code by updating the canonical child
# assignment table. No duplicate relationship is maintained in Design Code.
def _may_link_published(design_code):
    user = frappe.session.user
    return bool(
        can_manage_documents(user)
        and frappe.has_permission("Design Code", "write",
                                  doc=design_code, user=user)
        and frappe.has_permission("Design Code", "read",
                                  doc=design_code, user=user)
    )


@frappe.whitelist()
def can_link_published_document(design_code):
    if not isinstance(design_code, str) or not design_code:
        return False
    return _may_link_published(design_code)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_linkable_published_documents(
        doctype, txt, searchfield, start, page_len, filters):
    """Link picker; enforce Published status and read scope on results."""
    if doctype != "Design Document":
        return []
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    if not isinstance(filters, dict):
        return []
    design_code = filters.get("design_code")
    if (not isinstance(design_code, str) or not design_code
            or len(design_code) > 140
            or not _may_link_published(design_code)):
        return []
    needle = (txt or "").strip()
    if len(needle) > 100:
        return []
    per_page = min(25, max(1, int(page_len)))
    query = {
        "filters": {"publication_status": "Published"},
        "fields": ["name", "document_title", "document_type"],
        # Standard get_list applies document READ permissions. The selected
        # document is separately checked for WRITE before it can be linked.
        "order_by": "modified desc, name desc",
        "limit_start": max(0, int(start)),
        "limit_page_length": per_page,
    }
    if needle:
        term = "%" + needle + "%"
        query["or_filters"] = [
            ["Design Document", "name", "like", term],
            ["Design Document", "document_title", "like", term],
        ]
    docs = frappe.get_list("Design Document", **query)
    return [(doc.name, (doc.document_title or doc.name) + " — " +
             (doc.document_type or "")) for doc in docs]


@frappe.whitelist()
def published_document_link_details(design_code, document_name):
    """Document preview without exposing private data to unauthorized users."""
    if not _may_link_published(design_code):
        frappe.throw("Not authorized to link documents to this Design Code",
                     frappe.PermissionError)
    doc = frappe.get_doc("Design Document", document_name)
    doc.check_permission("write")
    if doc.publication_status != "Published":
        frappe.throw("Only Published Design Documents can be linked")
    return {
        "name": doc.name,
        "document_title": doc.document_title,
        "document_type": doc.document_type,
        "related_milestone_type": doc.related_milestone_type,
        "already_linked": any(row.design_code == design_code
                              for row in doc.get("assignments") or []),
    }


@frappe.whitelist(methods=["POST"])
def link_published_document(design_code, document_name, target_milestone_type=None):
    """Append a published assignment under locks using normal validation.

    Design Code lock precedes the document lock, consistent with detach.
    Frappe request transaction atomically saves the assignment and timeline.
    Never modify the original file or other assignment mappings.
    """
    from marina_custom_apps.design_management.clean_milestones.service import _lock_design
    if not all(isinstance(x, str) and 0 < len(x) <= 140
               for x in (design_code, document_name)):
        frappe.throw("Select a saved Design Code and Published Design Document")
    if target_milestone_type is not None and not isinstance(target_milestone_type, str):
        frappe.throw("Invalid milestone override")
    target_milestone_type = (target_milestone_type or "").strip() or None
    if target_milestone_type and len(target_milestone_type) > 140:
        frappe.throw("Invalid milestone override")
    _lock_design(design_code)
    if not _may_link_published(design_code):
        frappe.throw("Not authorized to link documents to this Design Code",
                     frappe.PermissionError)
    frappe.db.sql(
        "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
        (document_name,),
    )
    doc = frappe.get_doc("Design Document", document_name)
    doc.check_permission("write")
    if doc.publication_status != "Published":
        frappe.throw("Only Published Design Documents can be linked")
    # Linking a Published document must not depend on the Design's
    # milestone plan or a future milestone yet to be configured.
    # An explicitly requested override is checked against the global master.
    # A blank target is valid; the document's own Related Milestone Type,
    # when configured, remains the ordinary fallback.
    if target_milestone_type and not frappe.db.exists(
            "Design Milestone Type", target_milestone_type):
        frappe.throw("Unknown target milestone: " + target_milestone_type)
    if any(row.design_code == design_code for row in doc.get("assignments") or []):
        frappe.throw("This Design Code is already linked to the selected document")
    if len(doc.get("assignments") or []) >= 500:
        frappe.throw("Document has too many Design Code assignments")
    # The document's milestone is the default, with optional per-Design override.
    row = doc.append("assignments", {
        "design_code": design_code,
        "target_milestone_type": target_milestone_type or doc.related_milestone_type or None,
    })
    # Saving through the published DocType controller preserves the existing
    # assignments, validates access, and records the new relationship.
    doc.save()
    return {
        "design_code": design_code,
        "document": doc.name,
        "document_type": doc.document_type,
        "target_milestone_type": row.target_milestone_type,
        "publication_status": doc.publication_status,
    }
