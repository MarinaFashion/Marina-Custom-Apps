"""Permission-aware Pantone swatch lookup; master image is never copied."""
import frappe

@frappe.whitelist()
def color_swatch(pantone):
    if not frappe.has_permission("Design Code","read"):
        frappe.throw("Not authorized",frappe.PermissionError)
    return frappe.db.get_value("Marina Pantone",pantone,["color_image","color_name"],as_dict=True)

get_pantone_swatch=color_swatch
