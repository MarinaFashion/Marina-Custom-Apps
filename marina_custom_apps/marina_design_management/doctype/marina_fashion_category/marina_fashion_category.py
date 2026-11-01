import frappe
from frappe.utils.nestedset import NestedSet

class MarinaFashionCategory(NestedSet):
    nsm_parent_field = "parent_category"

    def validate(self):
        self.category_name = (self.category_name or "").strip()
        if not self.category_name:
            frappe.throw("Category Name is mandatory")
        self.is_group = 0 if self.parent_category else 1
        if self.parent_category:
            if self.parent_category == self.name:
                frappe.throw("A category cannot be its own parent")
            parent = frappe.get_doc("Marina Fashion Category", self.parent_category)
            if parent.parent_category:
                frappe.throw("Only two levels are supported: Category and Subcategory")
            if not parent.is_group:
                frappe.throw("Parent must be a category group")
            if not parent.is_active and self.is_active:
                frappe.throw("Cannot activate a subcategory under an inactive category")
        if not self.is_new() and self.get_db_value("is_active") and not self.is_active:
            if frappe.db.exists("Marina Fashion Category", {"parent_category":self.name, "is_active":1}):
                frappe.throw("Deactivate child subcategories before deactivating this category")
