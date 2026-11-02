import frappe
from frappe.model.document import Document


class DesignModuleRole(Document):
    def validate(self):
        if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
            frappe.throw("System Manager required to configure module roles", frappe.PermissionError)
        from marina_custom_apps.design_management.security.role_access import validate_module_role
        validate_module_role(self)

    def on_update(self):
        from marina_custom_apps.design_management.security.organization import clear_role_cache
        clear_role_cache()

    def on_trash(self):
        # Disabling is preferable to deletion; never orphan assignments or
        # a descendant's reporting structure.
        if frappe.db.exists("Design Module User Role", {
            "parent": "Design Management Settings",
            "parentfield": "module_user_roles",
            "module_role": self.name,
        }):
            frappe.throw("Remove all user-role assignments before deleting this role")
        if frappe.db.exists("Design Module Role", {"reports_to_role": self.name}):
            frappe.throw("Reassign subordinate roles before deleting this role")
        if self.name == "Administrator":
            frappe.throw("The root Administrator role cannot be deleted")

    def after_delete(self):
        from marina_custom_apps.design_management.security.organization import clear_role_cache
        clear_role_cache()
