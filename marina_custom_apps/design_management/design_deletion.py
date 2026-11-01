"""Authorized Design deletion, preserving published Design Documents.

The Design's *new* plan, executions and custody events are snapshotted first.
The operation never destroys ERPNext Items/Stock or unrelated uploaded files.
"""
import json
import frappe
from frappe.utils import now_datetime
from marina_custom_apps.design_management.security.role_access import require_action

MAX_DOCUMENTS=200
MAX_RECORDS=2000
MAX_BYTES=8_000_000


def _check_authorized(design):
    if frappe.session.user in ("Guest",None,""):
        frappe.throw("Sign in to delete a Design", frappe.PermissionError)
    require_action("Delete Design Code")
    if not frappe.has_permission("Design Code","delete",doc=design):
        frappe.throw("You lack Delete permission for this Design",frappe.PermissionError)


def _item_logs(design):
    logs=frappe.get_all("Design Item Creation",
        filters={"design_code":design.name},fields=["*"],limit_page_length=201)
    if len(logs)>200:
        frappe.throw("Too many Item creation logs for safe deletion")
    codes={str(x.item_code) for x in design.get("production_items") or [] if x.item_code}
    codes.update(str(x.template_item) for x in logs if x.template_item)
    if codes:
        existing=frappe.get_all("Item",filters={"name":["in",sorted(codes)]},
                                 pluck="name",limit_page_length=1)
        variants=frappe.get_all("Item",filters={"variant_of":["in",sorted(codes)]},
                                pluck="name",limit_page_length=1)
        if existing or variants:
            frappe.throw("ERPNext Item or variant exists. Design deletion is blocked.")
    return logs


def _records(design_code):
    tables={
        "plans":"Design Milestone Plan Entry",
        "executions":"Design Milestone Execution",
        "custody_events":"Design Milestone Custody Event",
    }
    snapshot={}
    for name,doctype in tables.items():
        rows=frappe.get_all(doctype,filters={"design_code":design_code},
                            fields=["*"],limit_page_length=MAX_RECORDS+1)
        if len(rows)>MAX_RECORDS:
            frappe.throw("Too many "+doctype+" records for safe deletion")
        snapshot[name]=[dict(x) for x in rows]
    return snapshot


def _assignments(design_code):
    result=frappe.get_all("Design Document Assignment",
        filters={"design_code":design_code,"parenttype":"Design Document",
                 "parentfield":"assignments"},
        fields=["name","parent"],limit_page_length=MAX_DOCUMENTS+1)
    if len(result)>MAX_DOCUMENTS:
        frappe.throw("Too many Design Document assignments for safe deletion")
    return result


def _lock_documents(design_code, rows):
    names=sorted({r.parent for r in rows})
    expected={name:sorted(r.name for r in rows if r.parent==name) for name in names}
    documents=[]
    for name in names:
        frappe.db.sql("SELECT name FROM `tabDesign Document` WHERE name=%s FOR UPDATE",
                      (name,))
        doc=frappe.get_doc("Design Document",name,for_update=True)
        relevant=[r for r in (doc.get("assignments") or [])
                  if r.design_code==design_code]
        if sorted(r.name for r in relevant)!=expected[name]:
            frappe.throw("Document assignments changed. Reload before deleting.")
        documents.append((doc,relevant))
    return documents


def _impact(snapshot,docs,logs):
    return {
        "planned_milestones":len(snapshot["plans"]),
        "completed_milestones":sum(x["plan_state"]=="Completed"
                                   for x in snapshot["plans"]),
        "custody_events":len(snapshot["custody_events"]),
        "related_documents":len(docs),
        "item_creation_logs":len(logs),
        "published_documents_preserved":True,
    }


@frappe.whitelist()
def can_delete_design(design_code):
    doc=frappe.get_doc("Design Code",design_code)
    from marina_custom_apps.design_management.security.role_access import can_action
    return bool(can_action("Delete Design Code")
                and frappe.has_permission("Design Code","delete",doc=doc))


@frappe.whitelist()
def preview_delete_design(design_code):
    doc=frappe.get_doc("Design Code",design_code)
    _check_authorized(doc)
    logs=_item_logs(doc)
    records=_records(design_code)
    assigns=_assignments(design_code)
    return _impact(records,assigns,logs)


def cleanup_before_design_trash(design, reason=None):
    """Common audited cleanup invoked by the Design Code on_trash lifecycle.

    Frappe's standard List bulk Delete calls frappe.delete_doc() per row.
    Every row therefore goes through this same cleanup as the Form button.
    Frappe already holds the Design Code's FOR UPDATE lock before on_trash.
    If a linked-record check later fails, that row's DB transaction rolls
    back the cleanup log and all child/assignment deletions together.

    No commits here: ERPNext controls the transaction boundary.
    """
    _check_authorized(design)
    design_code=design.name
    reason=(reason or "").strip() or (
        "Deleted through Design Code List"
        if getattr(frappe.flags, "in_bulk_delete", False)
        else "Deleted through standard Design Code delete"
    )
    if len(reason)>500:
        frappe.throw("Deletion reason is too long")

    item_logs=_item_logs(design)
    records=_records(design_code)
    links=_assignments(design_code)
    docs=_lock_documents(design_code,links)

    # Check ToDos that were created externally. The clean milestone engine
    # doesn't create ToDos; deleting such records would be unrelated work.
    if frappe.db.exists("ToDo",{"reference_type":"Design Code",
                                "reference_name":design_code}):
        frappe.throw("Resolve externally linked Design ToDos before deletion")

    snapshot={
        "design":design.as_dict(),
        "workflow":records,
        "documents":[{
            "name":doc.name,"publication_status":doc.publication_status,
            "removed_assignments":[r.as_dict() for r in rows],
        } for doc,rows in docs],
        "item_creation_logs":[dict(x) for x in item_logs],
    }
    packed=json.dumps(snapshot,default=str,ensure_ascii=False)
    if len(packed.encode("utf-8"))>MAX_BYTES:
        frappe.throw("Design snapshot exceeds safe deletion size")
    frappe.get_doc({
        "doctype":"Design Cleanup Log","design_code_ref":design_code,
        "operation":"Delete Design Code","performed_by":frappe.session.user,
        "performed_on":now_datetime(),"reason":reason,"snapshot":packed,
    }).insert(ignore_permissions=True)

    # Keep all file and shared Design Document records, detach only target
    # Design's child assignment links and write per-document audit rows.
    for document,rows in docs:
        frappe.db.delete("Design Document Assignment",
            {"name":["in",[r.name for r in rows]]})
        frappe.db.set_value("Design Document",document.name,
            "assignment_count",len(document.get("assignments") or [])-len(rows),
            update_modified=False)
        frappe.get_doc({
            "doctype":"Design Document Assignment Removal Log",
            "document_ref":document.name,"design_code_ref":design_code,
            "publication_status":document.publication_status,
            "removed_by":frappe.session.user,"removed_on":now_datetime(),
            "reason":reason,
        }).insert(ignore_permissions=True)
        frappe.clear_document_cache("Design Document",document.name)
    for log in item_logs:
        frappe.db.delete("Design Item Creation",{"name":log.name})
    for doctype in ("Design Milestone Custody Event","Design Milestone Execution",
                    "Design Milestone Plan Entry"):
        frappe.db.delete(doctype,{"design_code":design_code})

    return _impact(records,docs,item_logs)


@frappe.whitelist(methods=["POST"])
def delete_design(design_code, reason=None, confirm_design_code=None):
    """Existing Form Delete action; now shares on_trash with List Delete."""
    if not design_code or design_code!=confirm_design_code:
        frappe.throw("Confirm the exact Design Code before deletion")
    reason=(reason or "").strip() or "Deleted by authorized user"
    if len(reason)>500:
        frappe.throw("Deletion reason is too long")

    # Only the form API supplies a custom reason. The standard List Delete
    # receives its own reason; neither is allowed to bypass on_trash.
    previous_reason=getattr(frappe.flags,"marina_design_delete_reason",None)
    previous_result=getattr(frappe.flags,"marina_design_delete_result",None)
    frappe.flags.marina_design_delete_reason=reason
    frappe.flags.marina_design_delete_result=None
    try:
        # Uses Frappe's native Delete permission and on_trash hook.
        frappe.delete_doc("Design Code",design_code,ignore_missing=False)
        impact=getattr(frappe.flags,"marina_design_delete_result",None)
        if not impact or impact.get("deleted")!=design_code:
            frappe.throw("The Design cleanup did not complete")
        return impact
    finally:
        frappe.flags.marina_design_delete_reason=previous_reason
        frappe.flags.marina_design_delete_result=previous_result
