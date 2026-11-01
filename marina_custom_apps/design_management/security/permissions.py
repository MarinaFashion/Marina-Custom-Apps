"""Module-role-secured list and document access; no legacy role fallbacks."""
import frappe
from marina_custom_apps.design_management.security.role_access import (
    can_doctype, can_action,
)
from marina_custom_apps.design_management.security.organization import (
    has_overall_visibility, assigned_scope_sql, assigned_to_design, user_roles,
    is_head,
)


def is_manager(user):
    return user == "Administrator" or "System Manager" in frappe.get_roles(user) or is_head(user)


def roles(user):
    return set(frappe.get_roles(user))


def _op(ptype):
    return "read" if ptype in (None,"select","print","export") else ptype


def mood_board_query(user=None):
    user=user or frappe.session.user
    if can_doctype("Mood Board","read",user) is False:
        return "1=0"
    if has_overall_visibility(user):
        return ""
    esc=frappe.db.escape(user)
    return (
        "(EXISTS (SELECT 1 FROM `tabDesign Team Assignment` a "
        "WHERE a.parent=`tabMood Board`.name AND a.parenttype='Mood Board' "
        "AND a.parentfield='r22_team_assignments' AND a.active=1 "
        "AND a.user="+esc+") OR EXISTS (SELECT 1 FROM `tabDesign Code` d "
        "WHERE d.mood_board=`tabMood Board`.name AND "+
        assigned_scope_sql(user,"d")+"))"
    )


def mood_board_permission(doc,ptype=None,user=None):
    user=user or frappe.session.user
    if can_doctype("Mood Board",_op(ptype),user) is False:
        return False
    if has_overall_visibility(user) or ptype=="create":
        return True
    if ptype not in (None,"read","select","print","export","write"):
        return False
    if not doc.name:
        return False
    return bool(frappe.db.exists("Design Team Assignment",{
        "parent":doc.name,"parenttype":"Mood Board","active":1,"user":user,
    }) or frappe.db.exists("Design Code",{
        "mood_board":doc.name,"assigned_merchandiser":user,
    }) or frappe.db.exists("Design Code",{
        "mood_board":doc.name,"designer":user,
    }))


def design_code_query(user=None):
    user=user or frappe.session.user
    if can_doctype("Design Code","read",user) is False:
        return "1=0"
    return "" if has_overall_visibility(user) else assigned_scope_sql(user)


def design_code_permission(doc,ptype=None,user=None):
    user=user or frappe.session.user
    if can_doctype("Design Code",_op(ptype),user) is False:
        return False
    if ptype=="create":
        return bool(user_roles(user))
    scope=has_overall_visibility(user) or assigned_to_design(user,doc)
    if ptype=="delete":
        return bool(scope and can_action("Delete Design Code",user))
    if ptype in ("write",None,"read","select","print","export"):
        return bool(scope)
    return False


def document_query(user=None):
    user=user or frappe.session.user
    if can_doctype("Design Document","read",user) is False:
        return "1=0"
    if has_overall_visibility(user):
        return ""
    return (
        "(`tabDesign Document`.added_by="+frappe.db.escape(user)+
        " OR EXISTS (SELECT 1 FROM `tabDesign Document Assignment` da "
        "JOIN `tabDesign Code` d ON d.name=da.design_code "
        "WHERE da.parent=`tabDesign Document`.name AND da.parenttype='Design Document' "
        "AND "+assigned_scope_sql(user,"d")+"))"
    )


def document_permission(doc,ptype=None,user=None):
    user=user or frappe.session.user
    if can_doctype("Design Document",_op(ptype),user) is False:
        return False
    from marina_custom_apps.design_management.security.document_access import can_manage_documents
    if ptype=="create":
        return bool(can_manage_documents(user))
    if ptype=="write":
        # Uploading files on an unsaved document uses a temporary Frappe record.
        return bool(can_manage_documents(user) and (doc.is_new()
                    or doc.added_by==user or has_overall_visibility(user)))
    if ptype in (None,"read","select","print","export"):
        if has_overall_visibility(user) or doc.added_by==user:
            return True
        if not doc.name:
            return False
        codes = [r.design_code for r in (doc.get("assignments") or [])
                 if r.design_code][:500]
        if not codes:
            return False
        # get_list applies the effective Design Code scope. get_all would
        # bypass permission filtering and disclose unrelated files.
        return bool(frappe.get_list("Design Code",
            filters={"name": ["in", codes]}, fields=["name"],
            user=user, limit_page_length=1))
    return False


def colorway_query(user=None):
    user=user or frappe.session.user
    if can_doctype("Production Colorway","read",user) is False:
        return "1=0"
    if has_overall_visibility(user):
        return ""
    return ("EXISTS (SELECT 1 FROM `tabDesign Code` d "
            "WHERE d.name=`tabProduction Colorway`.design_code AND "+
            assigned_scope_sql(user,"d")+")")


def colorway_permission(doc,ptype=None,user=None):
    user=user or frappe.session.user
    if can_doctype("Production Colorway",_op(ptype),user) is False:
        return False
    if has_overall_visibility(user):
        return ptype in (None,"read","select","print","export")
    if not doc.design_code:
        return ptype=="create" and bool(user_roles(user))
    if ptype in (None,"read","select","print","export","write"):
        return frappe.has_permission("Design Code","read",doc=doc.design_code,user=user)
    return False


def module_reference_permission(doc,ptype=None,user=None):
    permitted=can_doctype(doc.doctype,_op(ptype),user or frappe.session.user)
    return False if permitted is False else None


def module_reference_query(user=None,doctype=None):
    return "1=0" if can_doctype(doctype,"read",user or frappe.session.user) is False else ""


def design_milestone_type_query(user=None):
    return module_reference_query(user,"Design Milestone Type")


def marina_fashion_category_query(user=None):
    return module_reference_query(user,"Marina Fashion Category")


def marina_pantone_query(user=None):
    return module_reference_query(user,"Marina Pantone")


def design_document_type_query(user=None):
    return module_reference_query(user,"Design Document Type")


def design_management_settings_query(user=None):
    return module_reference_query(user,"Design Management Settings")


def design_item_creation_query(user=None):
    return module_reference_query(user,"Design Item Creation")


def design_cleanup_log_query(user=None):
    return module_reference_query(user,"Design Cleanup Log")


def design_module_role_query(user=None):
    return module_reference_query(user,"Design Module Role")


def cost_breakdown_query(user=None):
    """Never expose factory prices through unrestricted List queries."""
    user = user or frappe.session.user
    from marina_custom_apps.marina_custom_apps.design_management.doctype.design_cost_breakdown.design_cost_breakdown import (
        _admin, _buyer, _module_roles, _commercial_all_scope,
    )
    if can_doctype("Design Cost Breakdown", "read", user) is False:
        return "1=0"
    if _admin(user):
        return ""
    permitted = _buyer(user) or "Head Of Merchandisers" in _module_roles(user)
    esc = frappe.db.escape(user)
    if permitted and _commercial_all_scope(user):
        return ""
    # Even Buying Managers must have a Design Code read scope unless their
    # module role explicitly gives All scope.
    return (
        "EXISTS (SELECT 1 FROM `tabDesign Code` d "
        "WHERE d.name=`tabDesign Cost Breakdown`.design_code AND "
        + assigned_scope_sql(user, "d") + ")"
        + ("" if permitted else " AND `tabDesign Cost Breakdown`.merchandiser=" + esc)
    )


def cost_breakdown_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    from marina_custom_apps.marina_custom_apps.design_management.doctype.design_cost_breakdown.design_cost_breakdown import (
        _admin, _buyer, _preparer, _allowed_design,
    )
    op = _op(ptype)
    if can_doctype("Design Cost Breakdown", op, user) is False:
        return False
    if not doc.design_code:
        return False
    design = frappe.get_doc("Design Code", doc.design_code)
    if not _allowed_design(design, user):
        return False
    can_edit = _preparer(design, user)
    can_review = _buyer(user)
    if ptype == "create":
        return bool(can_edit)
    if ptype == "delete":
        return bool(can_edit and doc.status in ("Draft", "Returned"))
    if ptype == "write":
        return bool(can_edit and doc.status in ("Draft", "Returned"))
    if ptype in (None, "read", "select", "print", "export"):
        return bool(can_edit or can_review)
    return False
