"""Read-only abbreviated Size catalog from ERPNext Item Attribute."""
import frappe

@frappe.whitelist()
def list_size_abbreviations(limit=200):
    if not frappe.has_permission("Design Code","read"):
        frappe.throw("Not authorized to access Design Code Sizes",frappe.PermissionError)
    limit=min(max(int(limit),1),500)
    return frappe.get_all("Item Attribute Value",
        filters={"parent":"Size","parenttype":"Item Attribute"},
        fields=["abbr","attribute_value as description"],
        order_by="idx asc",limit_page_length=limit)

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_size_abbreviations(doctype,txt,searchfield,start,page_len,filters):
    if not frappe.has_permission("Design Code","read"):
        return []
    return frappe.db.sql("""
        SELECT abbr,attribute_value FROM `tabItem Attribute Value`
         WHERE parent='Size' AND parenttype='Item Attribute'
           AND (abbr LIKE %(needle)s OR attribute_value LIKE %(needle)s)
         ORDER BY idx LIMIT %(start)s,%(count)s
    """,{"needle":"%"+(txt or "")+"%","start":int(start),
         "count":min(int(page_len),50)})
