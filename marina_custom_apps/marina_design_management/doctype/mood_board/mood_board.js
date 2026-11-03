/* Add the approved base team roles without disturbing existing assignments.
   A Design Team Assignment needs a User before the Mood Board can be saved.
   No roles/Users are persisted until the user saves the parent document. */
function marina_mood_missing_base_roles(base_roles, assignments) {
    const rows=assignments||[];
    const pairs=new Set(rows.filter(row=>row.module_role && row.user)
        .map(row=>row.module_role+"\\0"+row.user));
    const roles=new Set(rows.map(row=>row.module_role).filter(Boolean));
    return (base_roles||[]).filter(row=>
        row.user ? !pairs.has(row.module_role+"\\0"+row.user)
                 : !roles.has(row.module_role));
}

function marina_mood_base_roles_button(frm) {
    const field=frm.fields_dict.r22_team_assignments;
    const wrapper=field?.$wrapper;
    if(!wrapper?.length)return;
    const operation=frm.is_new()?"create":"write";
    if(typeof frm.has_perm==="function" && !frm.has_perm(operation))return;
    if(wrapper.find(".marina-add-base-team-roles").length)return;

    const button=$('<button type="button" class="btn btn-xs btn-default marina-add-base-team-roles"></button>')
        .text(__("Add Base Roles"));
    const label=wrapper.find(".control-label").first();
    if(label.length){
        // The Team Assignments field heading, to the right of its label.
        button.css({float:"right",margin:"0 0 6px 12px"}).insertAfter(label);
    }else{
        // Tolerate Frappe theme/layout differences without moving the grid.
        const holder=$('<div class="text-right" style="margin-bottom:8px"></div>')
            .append(button);
        const grid=wrapper.find(".form-grid").first();
        if(grid.length)holder.insertBefore(grid);
        else wrapper.prepend(holder);
    }

    button.on("click",()=>{
        if(button.prop("disabled"))return;
        const design=frm.doc.name;
        const was_new=frm.is_new();
        button.prop("disabled",true);
        frappe.call({
            method:"marina_custom_apps.design_management.clean_milestones.team.get_mood_board_base_roles",
            args:{mood_board:was_new?null:design}
        }).then(({message:template})=>{
            if(frm.doc.name!==design || frm.is_new()!==was_new)return;
            const missing=marina_mood_missing_base_roles(
                template,frm.doc.r22_team_assignments||[]);
            if(!missing.length){
                frappe.show_alert({
                    message:__("All configured Base Team assignments are already present."),
                    indicator:"blue"
                });
                return;
            }
            const existing=frm.doc.r22_team_assignments||[];
            const defaultRoles=new Set(existing.filter(row=>row.active && row.default_for_design)
                .map(row=>row.module_role));
            missing.forEach(role=>{
                const shouldDefault=Boolean(role.default_for_design) && !defaultRoles.has(role.module_role);
                if(shouldDefault)defaultRoles.add(role.module_role);
                frm.add_child("r22_team_assignments",{
                    module_role:role.module_role,
                    user:role.user||"",
                    active:1,
                    default_for_design:shouldDefault?1:0,
                    assignment_note:was_new?"":"Added from Base Roles template"
                });
            });
            frm.refresh_field("r22_team_assignments");
            frappe.show_alert({
                message:__("Added {0} Base Team assignments. Review and save the Mood Board.",[missing.length]),
                indicator:"green"
            },5);
        }).catch(error=>{
            console.warn("Marina Mood Board: unable to load Base Roles",error);
        }).finally(()=>button.prop("disabled",false));
    });
}

frappe.ui.form.on("Mood Board", {
    setup(frm) {
        frm.set_query("user", "r22_team_assignments", (doc, cdt, cdn) => ({
            query:"marina_custom_apps.design_management.security.participants.search_participant_users",
            filters:{module_role:locals[cdt]?.[cdn]?.module_role||""}
        }));
    },
    refresh(frm) {
        marina_mood_base_roles_button(frm);
        if(!frm.is_new()) {
            frm.add_custom_button(__("New Design Code"),()=>
                frappe.new_doc("Design Code",{mood_board:frm.doc.name}));
        }
    }
});
