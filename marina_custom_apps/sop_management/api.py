import frappe
from frappe import _
from frappe.utils import now_datetime, today


MANAGER_ROLES = {"SOP Manager", "System Manager"}
EDITOR_ROLES = {"SOP Editor", "SOP Manager", "System Manager"}


def _require_any_role(roles):
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
        version.append("sections", {"section_no": "1"})

    version.insert()
    return version.name


@frappe.whitelist()
def submit_for_review(version_name):
    _require_any_role(EDITOR_ROLES)
    doc = frappe.get_doc("SOP Version", version_name)
    if doc.status != "Draft":
        frappe.throw(_("Only a Draft SOP Version can be submitted for review."))
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
            "name", "display_title", "title_en", "title_ar", "sop_type",
            "department", "language", "summary", "keywords",
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
                for field in ("name", "display_title", "title_en", "title_ar", "summary", "keywords", "sop_type", "department")
            ).lower()
            return needle in haystack
        rows = [row for row in rows if matches(row)]

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

    return {
        "document": {
            "name": doc.name,
            "title_en": doc.title_en,
            "title_ar": doc.title_ar,
            "display_title": doc.display_title,
            "sop_type": doc.sop_type,
            "department": doc.department,
            "language": doc.language,
            "summary": doc.summary,
            "version_no": version.version_no,
            "effective_from": version.effective_from,
            "published_on": version.published_on,
        },
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
