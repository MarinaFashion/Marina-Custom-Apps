"""Tech Pack matches are specific to one Mood Board and one Designer.

A Design Document may contain multiple designers' files, but only the
matching designer's file is evidence for a given Design Code. The matching
key is immutable at publication. Existing legacy single-file Tech Packs
without a Mood Board continue using explicit assignment behavior.
"""
import frappe
from frappe.utils import now_datetime
from uuid import uuid4

MAX_MATCHES = 500


def designer_file(document, design):
    """Exact pinned file for a Tech Pack match, or None if not eligible."""
    if (document.document_type != "Tech Pack"
            or not document.get("tech_pack_mood_board")
            or document.publication_status != "Published"
            or document.get("superseded_by")
            or design.get("tech_pack_not_required")
            or document.tech_pack_mood_board != design.mood_board
            or not design.designer):
        return None
    files = [
        row.file for row in (document.get("additional_files") or [])
        if row.designer == design.designer and row.file
    ]
    return files[0] if len(files) == 1 else None


def candidate_documents(design, milestone_type, *, permission_filtered=True):
    """Bounded lookup; no per-Design or per-File repeated database queries.

    A candidate is valid only if its related milestone and unique Designer
    file match the Design Code. Multiple matches are deliberately ambiguous.
    """
    if design.get("tech_pack_not_required") or not design.designer:
        return []
    conditions = {
        "document_type": "Tech Pack",
        "tech_pack_mood_board": design.mood_board,
        "publication_status": "Published",
        "superseded_by": ["is", "not set"],
        "related_milestone_type": milestone_type,
    }
    loader = frappe.get_list if permission_filtered else frappe.get_all
    records = loader(
        "Design Document", filters=conditions, fields=["name"],
        limit_page_length=MAX_MATCHES + 1, order_by="modified desc, name desc",
    )
    if len(records) > MAX_MATCHES:
        frappe.throw("Too many Tech Pack documents match this Mood Board")
    if not records:
        return []
    names = [r.name for r in records]
    rows = frappe.get_all(
        "Design Document Additional File",
        filters={"parenttype": "Design Document",
                 "parentfield": "additional_files",
                 "parent": ["in", names],
                 "designer": design.designer},
        fields=["parent", "file"],
        limit_page_length=MAX_MATCHES + 1,
    )
    mapping = {}
    for row in rows:
        mapping.setdefault(row.parent, []).append(row.file)
    return [
        frappe._dict(name=record.name, evidence_file=mapping[record.name][0])
        for record in records
        if len(mapping.get(record.name, [])) == 1
    ]


def _insert_assignment(document_name, design_code, milestone_type):
    """System-controlled exact-match link; caller must hold document lock."""
    existing = frappe.db.exists(
        "Design Document Assignment",
        {"parent": document_name, "parenttype": "Design Document",
         "parentfield": "assignments", "design_code": design_code},
    )
    if existing:
        return False
    count = frappe.db.count(
        "Design Document Assignment",
        {"parent": document_name, "parenttype": "Design Document",
         "parentfield": "assignments"},
    )
    if count >= MAX_MATCHES:
        frappe.throw("Tech Pack exceeds 500 Design Code assignments")
    frappe.get_doc({
        "doctype": "Design Document Assignment",
        "name": uuid4().hex,
        "parent": document_name,
        "parenttype": "Design Document",
        "parentfield": "assignments",
        "idx": count + 1,
        "design_code": design_code,
        "target_milestone_type": milestone_type,
        "mood_board": frappe.db.get_value("Design Code", design_code, "mood_board"),
        "assigned_by": frappe.session.user,
        "assigned_on": now_datetime(),
    }).db_insert()
    frappe.db.set_value("Design Document", document_name, "assignment_count",
                        count + 1, update_modified=False)
    return True


def link_design(design):
    """At new Design Code save, link its unique applicable published Tech Pack.

    Does not expose any file to the Design's creator or permit an ambiguity
    to select an arbitrary Tech Pack. A re-publish can also link existing codes.
    """
    if design.get("tech_pack_not_required") or not design.mood_board or not design.designer:
        return None
    # This runs inside Design Code's transaction. All linked relationships
    # must agree with the persisted Design's Mood Board/Designer.
    documents = frappe.get_all(
        "Design Document",
        filters={"document_type": "Tech Pack",
                 "tech_pack_mood_board": design.mood_board,
                 "publication_status": "Published",
                 "superseded_by": ["is", "not set"]},
        fields=["name", "related_milestone_type"],
        limit_page_length=MAX_MATCHES + 1,
    )
    if len(documents) > MAX_MATCHES:
        return None
    relevant_ids = [row.name for row in documents]
    files = frappe.get_all(
        "Design Document Additional File",
        filters={"parenttype": "Design Document", "parentfield": "additional_files",
                 "parent": ["in", relevant_ids], "designer": design.designer},
        fields=["parent", "file"], limit_page_length=MAX_MATCHES + 1,
    ) if relevant_ids else []
    counts = {}
    for row in files:
        counts.setdefault(row.parent, []).append(row.file)
    matches = [
        row for row in documents
        if len(counts.get(row.name, [])) == 1
    ]
    # Do not silently pick between conflicting active Tech Packs.
    if len(matches) != 1:
        return None
    selected = matches[0]
    frappe.db.sql(
        "SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
        (selected.name,),
    )
    document = frappe.get_doc("Design Document", selected.name)
    if not designer_file(document, design):
        return None
    _insert_assignment(document.name, design.name, document.related_milestone_type)
    return document.name


def assert_unique_published_designer_files(document):
    """Prevent competing active Tech Pack versions for one Mood Board/Designer.

    Lock Mood Board first to serialize two concurrent publications targeting
    the same Mood Board. The previous version may still be Published while a
    legitimate replacement is being created in the same transaction.
    """
    if document.document_type != "Tech Pack" or not document.tech_pack_mood_board:
        return
    frappe.db.sql(
        "SELECT name FROM `tabMood Board` WHERE name=%s FOR UPDATE",
        (document.tech_pack_mood_board,),
    )
    designers = {r.designer for r in (document.get("additional_files") or [])
                 if r.designer and r.file}
    if not designers:
        frappe.throw("Select at least one Designer and Tech Pack File")
    others = frappe.get_all(
        "Design Document",
        filters={"name": ["!=", document.name],
                 "document_type": "Tech Pack",
                 "tech_pack_mood_board": document.tech_pack_mood_board,
                 "publication_status": "Published",
                 "superseded_by": ["is", "not set"]},
        fields=["name"], limit_page_length=MAX_MATCHES + 1,
    )
    if len(others) > MAX_MATCHES:
        frappe.throw("Too many published Tech Pack documents in this Mood Board")
    names = [row.name for row in others if row.name != document.supersedes_document]
    if not names:
        return
    overlapping = frappe.get_all(
        "Design Document Additional File",
        filters={"parenttype": "Design Document",
                 "parentfield": "additional_files",
                 "parent": ["in", names],
                 "designer": ["in", sorted(designers)]},
        fields=["parent", "designer"], limit_page_length=1,
    )
    if overlapping:
        frappe.throw(
            "Another active Published Tech Pack already covers one of these "
            "Designers in this Mood Board. Replace that published version "
            "instead of creating an ambiguous second mapping."
        )


def link_published_document(document):
    """At publication, link existing designs matching one of its Designers.

    Avoid touching milestone plans; publication does not advance milestones.
    """
    if document.document_type != "Tech Pack" or not document.tech_pack_mood_board:
        return 0
    designers = sorted({row.designer for row in
                        (document.get("additional_files") or []) if row.designer})
    if not designers:
        return 0
    codes = frappe.get_all("Design Code",
        filters={"mood_board": document.tech_pack_mood_board,
                 "designer": ["in", designers],
                 "tech_pack_not_required": 0},
        fields=["name", "mood_board", "designer", "tech_pack_not_required"],
        limit_page_length=MAX_MATCHES + 1)
    if len(codes) > MAX_MATCHES:
        frappe.throw("Tech Pack has more than 500 matching designs; split the publication")
    count = 0
    for design in codes:
        if designer_file(document, design):
            if _insert_assignment(document.name, design.name,
                                  document.related_milestone_type):
                count += 1
    return count
