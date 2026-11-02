/* Compatibility route only. All follow-up and planning use the grid. */
function marinaRedirectFollowup() {
    const route=frappe.get_route();
    if(route[0]!=="design-dynamic-followup")return;
    const parts=route.slice(1);
    if(!parts[0] && frappe.route_options?.design_code){
        parts[0]=frappe.route_options.design_code;
        delete frappe.route_options.design_code;
    }
    return frappe.set_route("design-followup-grid",...parts);
}
frappe.pages["design-dynamic-followup"].on_page_load=marinaRedirectFollowup;
frappe.pages["design-dynamic-followup"].on_page_show=marinaRedirectFollowup;
