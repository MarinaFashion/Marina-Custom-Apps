import frappe

MANAGER_ROLES={"SOP Manager","System Manager"}
EDITOR_ROLE="SOP Editor"

def _roles(user): return set(frappe.get_roles(user))
def _is_manager(user): return bool(_roles(user).intersection(MANAGER_ROLES))

def _ctx(user):
    key="_marina_sop_audience_context"
    c=getattr(frappe.local,key,None)
    if c and c.get("user")==user: return c
    c={"user":user,"employee":None,"designation":None,"department":None}
    if user not in {"Guest","Administrator"} and frappe.db.exists("DocType","Employee"):
        e=frappe.db.get_value("Employee",{"user_id":user,"status":"Active"},["name","designation","department"],as_dict=True)
        if e: c.update(employee=e.name,designation=e.designation,department=e.department)
    setattr(frappe.local,key,c)
    return c

def _row_match(row,c):
    return row.target == {"User":c["user"],"Employee":c["employee"],"Designation":c["designation"],"Department":c["department"]}.get(row.audience_type)

def _audience_allows(doc,user):
    if (doc.visibility or "Everyone")!="Restricted": return True
    c=_ctx(user); rows=doc.allowed_audience or doc.applicable_for or []
    return any(_row_match(r,c) for r in rows)

def sop_document_permission(doc,user=None,permission_type=None):
    user=user or frappe.session.user; permission_type=permission_type or "read"
    if _is_manager(user): return True
    if permission_type=="create": return None
    roles=_roles(user)
    if EDITOR_ROLE in roles and (doc.owner==user or doc.process_owner==user): return True
    if permission_type=="read": return bool(doc.status=="Published" and _audience_allows(doc,user))
    return False

def sop_version_permission(doc,user=None,permission_type=None):
    user=user or frappe.session.user; permission_type=permission_type or "read"
    if _is_manager(user): return True
    if permission_type=="create": return None
    if not doc.sop_document: return False
    parent=frappe.get_doc("SOP Document",doc.sop_document)
    roles=_roles(user)
    if EDITOR_ROLE in roles and (doc.owner==user or parent.owner==user or parent.process_owner==user): return True
    if permission_type=="read":
        return bool(doc.status=="Published" and parent.status=="Published" and parent.current_version==doc.name and _audience_allows(parent,user))
    return False

def _match_sql(alias,c):
    parts=[]
    for typ,val in (("User",c["user"]),("Employee",c["employee"]),("Designation",c["designation"]),("Department",c["department"])):
        if val:
            parts.append(f"({alias}.audience_type={frappe.db.escape(typ)} and {alias}.target={frappe.db.escape(val)})")
    return " or ".join(parts) or "0=1"

def _aud_sql(doc_alias,user):
    c=_ctx(user); ma=_match_sql("ra",c); mp=_match_sql("rp",c)
    return f"""(
coalesce({doc_alias}.visibility,'Everyone')!='Restricted'
or exists(select 1 from `tabSOP Audience Rule` ra where ra.parent={doc_alias}.name and ra.parenttype='SOP Document' and ra.parentfield='allowed_audience' and ({ma}))
or (
 not exists(select 1 from `tabSOP Audience Rule` rx where rx.parent={doc_alias}.name and rx.parenttype='SOP Document' and rx.parentfield='allowed_audience')
 and exists(select 1 from `tabSOP Audience Rule` rp where rp.parent={doc_alias}.name and rp.parenttype='SOP Document' and rp.parentfield='applicable_for' and ({mp}))
)
)"""

def sop_document_query(user=None):
    user=user or frappe.session.user
    if _is_manager(user): return ""
    eu=frappe.db.escape(user); audience=_aud_sql("`tabSOP Document`",user)
    editor="0=1"
    if EDITOR_ROLE in _roles(user):
        editor=f"(`tabSOP Document`.owner={eu} or `tabSOP Document`.process_owner={eu})"
    return f"({editor} or (`tabSOP Document`.status='Published' and {audience}))"

def sop_version_query(user=None):
    user=user or frappe.session.user
    if _is_manager(user): return ""
    eu=frappe.db.escape(user); audience=_aud_sql("sp",user)
    editor="0=1"
    if EDITOR_ROLE in _roles(user):
        editor=f"(`tabSOP Version`.owner={eu} or sp.owner={eu} or sp.process_owner={eu})"
    return f"""exists(select 1 from `tabSOP Document` sp where sp.name=`tabSOP Version`.sop_document and (
{editor} or (`tabSOP Version`.status='Published' and sp.status='Published' and sp.current_version=`tabSOP Version`.name and {audience})
))"""