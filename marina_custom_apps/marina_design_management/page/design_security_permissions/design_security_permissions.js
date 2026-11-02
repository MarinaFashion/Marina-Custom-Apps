frappe.pages["design-security-permissions"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper, title: __("Design Security & Permissions"), single_column: true
    });
    if (!frappe.user.has_role("System Manager") && frappe.session.user !== "Administrator") {
        $(page.body).html('<div class="alert alert-warning">' +
            __("System Manager is required to configure module security.") + '</div>');
        return;
    }
    $(page.body).html(
        '<div class="card p-4 mb-3"><h4>'+__("Role-Based Access Control")+'</h4>'+
        '<p class="text-muted">'+__("Define a module role, configure DocType permissions and workflow actions, then assign users in Design Management Settings. Existing access remains until enforcement is enabled.")+'</p>'+
        '<p><button class="btn btn-primary mdm-roles">'+__("Manage Module Roles")+'</button> '+
        '<button class="btn btn-default mdm-hierarchy">'+__("Role Hierarchy")+'</button> '+
        '<button class="btn btn-default mdm-users">'+__("Assign Users / Enable Enforcement")+'</button></p></div>');
    $(page.body).find(".mdm-roles").on("click",()=>frappe.set_route("List","Design Module Role"));
    $(page.body).find(".mdm-hierarchy").on("click",()=>frappe.set_route("design-role-hierarchy"));
    $(page.body).find(".mdm-users").on("click",()=>frappe.set_route("Form","Design Management Settings"));
};
