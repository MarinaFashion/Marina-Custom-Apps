import json, frappe
from frappe import _

def eligible_store_warehouses(company):
    settings=frappe.get_single("DC Dispatch Settings"); f=settings.warehouse_is_store_field
    if not frappe.get_meta("Warehouse").get_field(f): frappe.throw(_("Configured Warehouse store field {0} does not exist.").format(f))
    return frappe.get_all("Warehouse",filters={"company":company,"disabled":0,"is_group":0,f:1},pluck="name",order_by="name asc",limit_page_length=0)

def warehouse_allowed_users(warehouse):
    meta=frappe.get_meta("Warehouse")
    tables=[f for f in meta.fields if f.fieldtype=="Table" and "user" in ((f.fieldname or "")+" "+(f.label or "")).lower() and "allow" in ((f.fieldname or "")+" "+(f.label or "")).lower()]
    if not tables: return []
    doc=frappe.get_doc("Warehouse",warehouse); users=set()
    for tf in tables:
        cm=frappe.get_meta(tf.options)
        candidates=[f.fieldname for f in cm.fields if (f.fieldtype=="Link" and f.options=="User") or "user" in (f.fieldname or "").lower()]
        for row in doc.get(tf.fieldname) or []:
            for fn in candidates:
                v=row.get(fn)
                if v and frappe.db.exists("User",v): users.add(v); break
    return sorted(users)

def assignment_payload(company):
    out=[]
    for wh in eligible_store_warehouses(company):
        users=warehouse_allowed_users(wh)
        out.append({"warehouse":wh,"users":users,"auto_user":users[0] if len(users)==1 else None,"needs_selection":len(users)>1,"missing_user":len(users)==0})
    return out

def validate_assignment(warehouse,user):
    users=warehouse_allowed_users(warehouse)
    if not user: frappe.throw(_("Assigned Store User is required for {0}.").format(warehouse))
    if user not in users: frappe.throw(_("User {0} is not in Warehouse Users Allowed for {1}.").format(user,warehouse))

def parse_assignments(v): return json.loads(v or "{}") if isinstance(v,str) else (v or {})

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def allowed_user_query(doctype, txt, searchfield, start, page_len, filters):
    """Return only enabled users allowed for the selected Warehouse."""
    warehouse = (filters or {}).get("warehouse")
    if not warehouse:
        return []

    users = warehouse_allowed_users(warehouse)
    if not users:
        return []

    txt = (txt or "").strip()
    return frappe.get_all(
        "User",
        filters={
            "enabled": 1,
            "name": ["in", users],
        },
        or_filters={
            "name": ["like", f"%{txt}%"],
            "full_name": ["like", f"%{txt}%"],
        },
        fields=["name", "full_name"],
        order_by="full_name asc, name asc",
        limit_start=int(start or 0),
        limit_page_length=int(page_len or 20),
        as_list=True,
    )
