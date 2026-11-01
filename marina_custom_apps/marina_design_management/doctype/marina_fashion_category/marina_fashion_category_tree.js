frappe.treeview_settings["Marina Fashion Category"] = {
    breadcrumb: "Marina Design Management",
    title: __("Fashion Categories"),
    get_tree_nodes: "frappe.desk.treeview.get_children",
    add_tree_node: "frappe.desk.treeview.add_node",
    fields: [
        {fieldtype: "Data", fieldname: "category_name", label: __("Category Name"), reqd: 1},
        {fieldtype: "Check", fieldname: "is_active", label: __("Active"), default: 1}
    ],
    ignore_fields: ["parent_category"]
};
