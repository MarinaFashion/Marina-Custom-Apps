import frappe
from frappe import _
from frappe.utils import now_datetime, today

from marina_custom_apps.sop_management.doctype.sop_version.sop_version import (
    ADVANCED_HTML_MODE,
    assert_latest_version,
    sanitize_sop_html,
    write_version_action_log,
)


MANAGER_ROLES = {"SOP Manager", "System Manager"}
EDITOR_ROLES = {"SOP Editor", "SOP Manager", "System Manager"}


def _require_any_role(roles):
    if frappe.session.user == "Administrator":
        return
    user_roles = set(frappe.get_roles())
    if not user_roles.intersection(roles):
        frappe.throw(_("You are not permitted to perform this SOP action."), frappe.PermissionError)


def _ensure_read_permission(doctype, name=None):
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def create_new_version(sop_document):
    _require_any_role(EDITOR_ROLES)
    doc = frappe.get_doc("SOP Document", sop_document)
    if not doc.has_permission("read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    source = None
    if doc.current_version and frappe.db.exists("SOP Version", doc.current_version):
        source = frappe.get_doc("SOP Version", doc.current_version)

    version = frappe.new_doc("SOP Version")
    version.sop_document = doc.name
    version.language = doc.language or "Bilingual"
    version.status = "Draft"
    if source:
        version.previous_version = source.name
        version.content_mode = source.content_mode or "Standard Rich Text"
        if version.content_mode == ADVANCED_HTML_MODE:
            version.html_content = source.html_content
        for row in source.sections:
            version.append(
                "sections",
                {
                    "section_no": row.section_no,
                    "heading_en": row.heading_en,
                    "heading_ar": row.heading_ar,
                    "content_en": row.content_en,
                    "content_ar": row.content_ar,
                },
            )
    else:
        version.content_mode = "Standard Rich Text"
        version.append("sections", {"section_no": "1"})

    version.insert()
    return version.name


@frappe.whitelist()
def preview_advanced_html(html_content=None):
    _require_any_role(EDITOR_ROLES)
    return sanitize_sop_html(html_content or "")

@frappe.whitelist()
def submit_for_review(version_name):
    _require_any_role(EDITOR_ROLES)
    doc = frappe.get_doc("SOP Version", version_name)
    if doc.status != "Draft":
        frappe.throw(_("Only a Draft SOP Version can be submitted for review."))

    # Drafts may be incomplete; review cannot start without controlled metadata.
    parent = frappe.get_doc("SOP Document", doc.sop_document)
    if not (parent.document_no or "").strip():
        frappe.throw(_("Document No. is required before Submit for Review."))
    parent.validate_access_configuration(require_audience=True)
    doc.validate_content_completeness()

    frappe.flags.in_sop_publication = True
    try:
        doc.status = "Under Review"
        doc.save()
    finally:
        frappe.flags.in_sop_publication = False
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def approve_version(version_name):
    _require_any_role(MANAGER_ROLES)
    doc = frappe.get_doc("SOP Version", version_name)
    if doc.status != "Under Review":
        frappe.throw(_("Only an Under Review SOP Version can be approved."))
    frappe.flags.in_sop_publication = True
    try:
        doc.status = "Approved"
        doc.approved_by = frappe.session.user
        doc.approved_on = now_datetime()
        doc.save()
    finally:
        frappe.flags.in_sop_publication = False
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def publish_version(version_name):
    _require_any_role(MANAGER_ROLES)
    doc = frappe.get_doc("SOP Version", version_name)
    if doc.status != "Approved":
        frappe.throw(_("Only an Approved SOP Version can be published."))

    parent = frappe.get_doc("SOP Document", doc.sop_document)
    if not (parent.document_no or "").strip():
        frappe.throw(_("Document No. is required before publication."))
    parent.validate_access_configuration(require_audience=True)

    frappe.flags.in_sop_publication = True
    try:
        previous_name = parent.current_version
        if previous_name and previous_name != doc.name and frappe.db.exists("SOP Version", previous_name):
            previous = frappe.get_doc("SOP Version", previous_name)
            if previous.status == "Published":
                previous.status = "Superseded"
                previous.effective_to = today()
                previous.save()

        if not doc.effective_from:
            doc.effective_from = today()
        doc.status = "Published"
        doc.published_by = frappe.session.user
        doc.published_on = now_datetime()
        doc.save()

        parent.current_version = doc.name
        parent.current_version_no = doc.version_no
        parent.status = "Published"
        parent.save()
    finally:
        frappe.flags.in_sop_publication = False

    return {
        "sop_document": parent.name,
        "version": doc.name,
        "version_no": doc.version_no,
        "status": doc.status,
    }


def _restore_previous_published_version(parent, current_version):
    rows = frappe.get_all(
        "SOP Version",
        filters={
            "sop_document": parent.name,
            "version_no": ["<", current_version.version_no],
            "status": ["in", ["Published", "Superseded"]],
        },
        fields=["name", "version_no"],
        order_by="version_no desc",
        limit_page_length=1,
    )

    if rows:
        previous = frappe.get_doc("SOP Version", rows[0].name)
        previous.status = "Published"
        previous.effective_to = None
        previous.save(ignore_permissions=True)

        parent.current_version = previous.name
        parent.current_version_no = previous.version_no
        parent.status = "Published"
        parent.save(ignore_permissions=True)
        return previous.name

    parent.current_version = None
    parent.current_version_no = 0
    parent.status = "Draft"
    parent.save(ignore_permissions=True)
    return None


@frappe.whitelist()
def unpublish_version(version_name, reason):
    _require_any_role(MANAGER_ROLES)

    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Unpublish Reason is required."))

    doc = frappe.get_doc("SOP Version", version_name)
    assert_latest_version(doc)

    if doc.status != "Published":
        frappe.throw(_("Only the latest Published SOP Version can be unpublished."))

    parent = frappe.get_doc("SOP Document", doc.sop_document)
    if parent.current_version != doc.name:
        frappe.throw(
            _("Published SOP Version {0} is not the current version of {1}.").format(
                frappe.bold(doc.name), frappe.bold(parent.name)
            )
        )

    frappe.flags.in_sop_publication = True
    try:
        restored_version = _restore_previous_published_version(parent, doc)

        doc.status = "Draft"
        doc.effective_from = None
        doc.effective_to = None
        doc.approved_by = None
        doc.approved_on = None
        doc.published_by = None
        doc.published_on = None
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.in_sop_publication = False

    write_version_action_log(
        doc,
        action="Unpublished",
        reason=reason,
        previous_status="Published",
        restored_version=restored_version,
    )

    return {
        "name": doc.name,
        "status": doc.status,
        "previous_status": "Published",
        "restored_version": restored_version,
    }


@frappe.whitelist()
def cancel_version(version_name, reason):
    _require_any_role(MANAGER_ROLES)

    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Cancellation Reason is required."))

    doc = frappe.get_doc("SOP Version", version_name)
    assert_latest_version(doc)

    if doc.status == "Published":
        frappe.throw(_("A Published SOP Version must be unpublished before it can be cancelled."))
    if doc.status == "Superseded":
        frappe.throw(_("A Superseded SOP Version cannot be cancelled while it is part of published history."))
    if doc.status == "Cancelled":
        frappe.throw(_("This SOP Version is already cancelled."))

    previous_status = doc.status

    frappe.flags.in_sop_publication = True
    try:
        doc.status = "Cancelled"
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.in_sop_publication = False

    write_version_action_log(
        doc,
        action="Cancelled",
        reason=reason,
        previous_status=previous_status,
    )

    return {
        "name": doc.name,
        "status": doc.status,
        "previous_status": previous_status,
        "restored_version": None,
    }


@frappe.whitelist()
def archive_sop(sop_document):
    _require_any_role(MANAGER_ROLES)
    parent = frappe.get_doc("SOP Document", sop_document)
    if parent.status != "Published":
        frappe.throw(_("Only a Published SOP can be archived."))

    frappe.flags.in_sop_publication = True
    try:
        if parent.current_version and frappe.db.exists("SOP Version", parent.current_version):
            version = frappe.get_doc("SOP Version", parent.current_version)
            if version.status == "Published" and not version.effective_to:
                version.effective_to = today()
                version.save()
        parent.status = "Archived"
        parent.save()
    finally:
        frappe.flags.in_sop_publication = False

    return {"sop_document": parent.name, "status": parent.status}


@frappe.whitelist()
def search_library(search_text=None, sop_type=None, department=None, language=None, limit=100):
    if not frappe.has_permission("SOP Document", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    limit = min(max(int(limit or 100), 1), 200)
    filters = {"status": "Published", "current_version": ["is", "set"]}
    if sop_type:
        filters["sop_type"] = sop_type
    if department:
        filters["department"] = department
    if language:
        filters["language"] = language

    # get_list respects Frappe permissions/User Permissions. Do not expose
    # restricted SOP titles/summaries through the Library search results.
    rows = frappe.get_list(
        "SOP Document",
        filters=filters,
        fields=[
            "name", "document_no", "display_title", "title_en", "title_ar", "sop_type",
            "department", "language", "summary", "summary_ar", "keywords", "keywords_ar",
            "current_version", "current_version_no", "modified",
        ],
        order_by="sop_type asc, display_title asc",
        limit_page_length=500,
    )

    needle = (search_text or "").strip().lower()
    if needle:
        def matches(row):
            haystack = " ".join(
                str(row.get(field) or "")
                for field in ("name", "document_no", "display_title", "title_en", "title_ar", "summary", "summary_ar", "keywords", "keywords_ar", "sop_type", "department")
            ).lower()
            return needle in haystack
        rows = [row for row in rows if matches(row)]

    type_rows = frappe.get_all(
        "SOP Type", filters={"is_active": 1},
        fields=["name", "sort_order"], order_by="sort_order asc, type_name asc"
    )
    type_order = {row.name: (row.sort_order or 0) for row in type_rows}
    rows.sort(key=lambda row: (
        type_order.get(row.sop_type, 999999),
        (row.sop_type or "").lower(),
        (row.display_title or "").lower(),
    ))
    return rows[:limit]


@frappe.whitelist()
def get_published_sop(sop_document):
    doc = frappe.get_doc("SOP Document", sop_document)
    if not doc.has_permission("read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    if doc.status != "Published" or not doc.current_version:
        frappe.throw(_("This SOP does not have a published version."))

    version = frappe.get_doc("SOP Version", doc.current_version)
    if version.status != "Published":
        frappe.throw(_("The current SOP Version is not published."))

    history = frappe.get_list(
        "SOP Version",
        filters={"sop_document": doc.name},
        fields=[
            "name", "version_no", "status", "effective_from",
            "approved_by", "published_on", "change_summary",
        ],
        order_by="version_no desc",
        limit_page_length=100,
    )

    return {
        "document": {
            "name": doc.name,
            "document_no": doc.document_no,
            "title_en": doc.title_en,
            "title_ar": doc.title_ar,
            "display_title": doc.display_title,
            "sop_type": doc.sop_type,
            "department": doc.department,
            "language": doc.language,
            "summary": doc.summary,
            "summary_ar": doc.summary_ar,
            "keywords": doc.keywords,
            "keywords_ar": doc.keywords_ar,
            "current_version": version.name,
            "version_no": version.version_no,
            "effective_from": version.effective_from,
            "approved_by": version.approved_by,
            "published_on": version.published_on,
            "content_mode": version.content_mode or "Standard Rich Text",
            "html_content": version.html_content if version.content_mode == ADVANCED_HTML_MODE else None,
        },
        "revision_history": history,
        "sections": [
            {
                "section_no": row.section_no,
                "heading_en": row.heading_en,
                "heading_ar": row.heading_ar,
                "content_en": row.content_en,
                "content_ar": row.content_ar,
            }
            for row in version.sections
        ],
    }
