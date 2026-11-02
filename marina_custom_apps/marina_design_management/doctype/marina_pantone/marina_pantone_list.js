// Frappe v15 does NOT allow in_list_view on Attach Image.
// Display a thumbnail using the DocType's image_field, not a regular list column.
frappe.listview_settings["Marina Pantone"] = {
    add_fields: ["color_image", "color_name", "color_system", "is_active"],
};
