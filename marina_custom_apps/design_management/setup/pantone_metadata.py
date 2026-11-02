"""Repair persisted Pantone metadata after DocType model sync.

Only the invalid image list setting and DocType import flag are changed.
Existing Pantone documents, image links, and other customizations are preserved.
"""

import frappe


def repair_pantone_import_metadata():
    doctype = "Marina Pantone"
    if not frappe.db.exists("DocType", doctype):
        return

    if not frappe.db.get_value("DocType", doctype, "allow_import"):
        frappe.db.set_value("DocType", doctype, "allow_import", 1, update_modified=False)

    field = frappe.db.get_value(
        "DocField",
        {"parent": doctype, "fieldname": "color_image"},
        ["name", "in_list_view"],
        as_dict=True,
    )
    if field and field.in_list_view:
        frappe.db.set_value("DocField", field.name, "in_list_view", 0, update_modified=False)

    # Property Setters override DocField properties in effective DocType metadata.
    setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": doctype,
            "field_name": "color_image",
            "property": "in_list_view",
        },
        fields=["name", "value"],
    )
    for setter in setters:
        if str(setter.value) != "0":
            frappe.db.set_value(
                "Property Setter", setter.name, "value", "0", update_modified=False
            )

    frappe.clear_cache(doctype=doctype)
