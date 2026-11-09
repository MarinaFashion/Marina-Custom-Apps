/* The editable Design Team Snapshot is the only ownership input.
   Read scoped defaults from the selected Mood Board; never re-fetch on every
   refresh or overwrite employee edits while the Design is unsaved. */
function marina_load_mood_board_team(frm, board) {
    if (!frm.is_new() || !board || frm.doc.mood_board !== board) return;
    if (frm.__marina_team_loaded_board === board) return;
    const before=(frm.doc.r22_team_assignments||[]).length;
    const previous=frm.__marina_team_loaded_board;
    const fetchTeam=()=>{
        const ticket=(frm.__marina_team_ticket||0)+1;
        frm.__marina_team_ticket=ticket;
        frappe.call({
            method:"marina_custom_apps.design_management.clean_milestones.team.preview_mood_board_team",
            args:{mood_board:board}
        }).then(({message:assignments})=>{
            if (!frm.is_new() || frm.doc.mood_board!==board ||
                    frm.__marina_team_ticket!==ticket) return;
            // Do not replace user-entered rows while this request was loading.
            if (!before && (frm.doc.r22_team_assignments||[]).length) return;
            frm.clear_table("r22_team_assignments");
            (assignments||[]).forEach(item=>{
                if(item.user && item.user_username){
                    frappe.utils.add_link_title("User",item.user,item.user_username);
                }
                const row=frm.add_child("r22_team_assignments");
                row.module_role=item.module_role;
                row.user=item.user;
                row.active=1;
                row.default_for_design=1;
                row.assignment_note=item.assignment_note;
            });
            frm.__marina_team_loaded_board=board;
            // Distinguish an intentionally edited/cleared snapshot from an
            // uninitialized new Design when the server validates first Save.
            frm.doc.r22_team_snapshot_applied=1;
            frm.refresh_field("r22_team_assignments");
            if (!(assignments||[]).length) {
                frappe.show_alert({
                    message:__("No unambiguous defaults in this Mood Board. An authorized manager must assign the team."),
                    indicator:"orange"
                });
            }
        }).catch(()=>{
            // Do not mark the board as loaded if the scoped lookup failed.
            if (frm.__marina_team_ticket===ticket)frm.__marina_team_loaded_board=null;
        });
    };
    if (before) {
        frappe.confirm(
            __("Replace the current unsaved Design Team with defaults from {0}?",[board]),
            fetchTeam,
            ()=>{if (previous && frm.doc.mood_board===board)frm.set_value("mood_board",previous);}
        );
    } else {
        fetchTeam();
    }
}

function marina_refresh_creation_date(frm) {
    const ticket = (frm.__marina_date_ticket || 0) + 1;
    frm.__marina_date_ticket = ticket;
    if (frm.is_new()) {
        frm.set_df_property("creation_date", "read_only", 0);
        if (!frm.doc.creation_date) {
            frm.set_value("creation_date", frappe.datetime.get_today());
        }
        return;
    }
    const design = frm.doc.name;
    frm.set_df_property("creation_date", "read_only", 1);
    frappe.call({
        method: "marina_custom_apps.marina_design_management.doctype.design_code.design_code.can_edit_creation_date",
        args: {design_code: design}
    }).then(({message}) => {
        if (frm.is_new() || frm.doc.name !== design ||
            frm.__marina_date_ticket !== ticket) return;
        frm.set_df_property("creation_date", "read_only", message ? 0 : 1);
    }).catch(() => {
        if (frm.doc.name === design && frm.__marina_date_ticket === ticket) {
            frm.set_df_property("creation_date", "read_only", 1);
        }
    });
}

function marina_clean_render_milestones(frm) {
    const wrapper=frm.fields_dict.milestone_overview?.$wrapper;
    if(!wrapper)return;
    if(frm.is_new()){wrapper.text(__("Save this Design Code to select milestones."));return;}
    const name=frm.doc.name;
    const generation=frm.__marina_menu_version;
    frappe.call({method:"marina_custom_apps.design_management.clean_milestones.api.overview",
                 args:{design_code:name}}).then(({message})=>{
        if(frm.doc.name!==name || frm.__marina_menu_version!==generation)return;
        if(!message?.can_plan){
            frm.remove_custom_button(__("Create Milestones"),__("Actions"));
            delete frm.__marina_design_buttons?.Actions?.["Create Milestones"];
        }
        const esc=v=>frappe.utils.escape_html(String(v??""));
        const rows=(message?.current||[]).map(x=>'<tr><td>'+esc(x.milestone_type)+'</td><td>'+
            esc(x.status)+'</td><td>'+esc(x.current_custodian_username||"")+'</td></tr>').join("");
        wrapper.html(rows?'<table class="table table-bordered"><thead><tr><th>'+__("Milestone")+
          '</th><th>'+__("Step")+'</th><th>'+__("Custodian")+
          '</th></tr></thead><tbody>'+rows+'</tbody></table>':
          '<p>'+__("No active milestones. Use Actions > Create Milestones to create a plan.")+'</p>');
    }).catch(()=>{
        if(frm.doc.name!==name || frm.__marina_menu_version!==generation)return;
        frm.remove_custom_button(__("Create Milestones"),__("Actions"));
        delete frm.__marina_design_buttons?.Actions?.["Create Milestones"];
        wrapper.text(__("Unable to load milestones. Check Module Role assignments."));
    });
}

/* Deterministic menu order despite independently resolved permission requests.
   Keep action buttons gated by their existing server-side permission checks. */
const marina_design_menu_order={
    Actions:["Create Milestones","Milestone Follow up","Return to Milestone",
             "Clear Related Milestones","Edit Design Responsibility","Delete Design"],
    Document:["Show Linked Documents","Link To Published Document","New Design Document"]
};
function marina_design_button(frm,label,fn,group){
    const control=frm.add_custom_button(__(label),fn,__(group));
    const registry=frm.__marina_design_buttons||(frm.__marina_design_buttons={});
    const entries=registry[group]||(registry[group]={});
    entries[label]=control;
    const sequence=(marina_design_menu_order[group]||[])
        .map(name=>entries[name]).filter(button=>button?.jquery && button.length);
    if(sequence.length>1){
        const parent=sequence[0].parent();
        if(parent.length && sequence.every(button=>button.parent()[0]===parent[0])){
            sequence.forEach(button=>button.appendTo(parent));
        }
    }
    return control;
}

/* Clear the entire milestone workflow, but never the Design Code, linked
   evidence documents, production records or team. The backend holds the
   complete history in an immutable Design Cleanup Log first. */
function marina_open_clear_milestones_dialog(frm, design){
    if(frm.is_dirty()){
        frappe.msgprint(__("Save or discard Design Code changes before clearing milestones."));
        return;
    }
    const endpoint="marina_custom_apps.design_management.clean_milestones.clear_related";
    frappe.call({
        method:endpoint+".preview_clear_related_milestones",
        args:{design_code:design},freeze:true
    }).then(({message:preview})=>{
        if(frm.doc.name!==design || !preview)return;
        const state=preview.designs?.[0];
        if(!state?.has_milestones){
            frappe.msgprint(__("No related milestones were found for this Design Code."));
            return;
        }
        const esc=frappe.utils.escape_html;
        const impact='<p><b>'+esc(__("Clear all milestones for {0}?",[design]))+'</b></p>'+
            '<ul><li>'+esc(__("Milestone plans: {0}",[state.plans]))+'</li>'+
            '<li>'+esc(__("Executions: {0}",[state.executions]))+'</li>'+
            '<li>'+esc(__("Custody history events: {0}",[state.events]))+'</li></ul>'+
            '<p class="text-danger">'+esc(__("All active, completed and future milestone records will be removed. This cannot be undone from the screen."))+'</p>'+
            '<p>'+esc(__("A permanent cleanup audit snapshot is retained. Linked Design Documents, published files, team assignments and production data remain unchanged."))+'</p>'+
            '<p>'+esc(__("Creation Date becomes editable again, and Create Milestones can be used to rebuild the plan."))+'</p>';
        const dlg=new frappe.ui.Dialog({
            title:__("Clear Related Milestones"),
            size:"large",
            fields:[
                {fieldname:"impact",fieldtype:"HTML",options:impact},
                {fieldname:"reason",fieldtype:"Small Text",reqd:1,
                    label:__("Reason for Clearing"),
                    description:__("Required: 10 to 500 characters; permanently retained in the cleanup audit.")},
                {fieldname:"confirmed",fieldtype:"Check",reqd:1,
                    label:__("I understand that all milestone workflow history will be cleared")}
            ],
            primary_action_label:__("Clear Related Milestones"),
            primary_action(values){
                const reason=(values.reason||"").trim();
                if(reason.length<10 || reason.length>500 || !values.confirmed){
                    frappe.msgprint(__("Confirm the reset and enter a reason of 10–500 characters."));
                    return;
                }
                const btn=dlg.get_primary_btn();
                btn.prop("disabled",true);
                frappe.call({
                    method:endpoint+".clear_related_milestones",
                    type:"POST",
                    args:{design_code:design,reason,
                          expected_revision:state.revision,confirm:1},
                    freeze:true,
                    freeze_message:__("Archiving and clearing milestone workflow")
                }).then(({message:result})=>{
                    if(!result)return;
                    dlg.hide();
                    frappe.show_alert({indicator:"green",
                        message:__("Related milestones cleared. You may create a new plan.")},5);
                    frm.reload_doc();
                }).finally(()=>btn.prop("disabled",false));
            }
        });
        dlg.show();
    }).catch(error=>{
        console.warn("Marina Design: unable to preview milestone reset",error);
    });
}

/* Design Code: centralized documents + practical Production Items and size allocations. */

/* The server owns workflow mode. Legacy controls appear only for legacy
   designs; new Release 22 designs never have two competing follow-up menus. */
frappe.ui.form.on("Design Code", {
    setup(frm) {
        frm.set_query("user", "r22_team_assignments", (doc, cdt, cdn) => ({
            query:"marina_custom_apps.design_management.security.participants.search_participant_users",
            filters:{module_role:locals[cdt]?.[cdn]?.module_role||""}
        }));
        frm.set_query("category", () => ({
            filters:{parent_category:["is","not set"],is_active:1}
        }));
        frm.set_query("subcategory", () => ({
            filters:{parent_category:frm.doc.category || "",is_active:1}
        }));
        // The actual Size cell is a Link field, not a free-text Data input.
        frm.set_query("size", "sizes", () => ({
            filters: {is_active: 1}
        }));
    },
    onload_post_render(frm) {
        if (frm.is_new() && frm.doc.mood_board &&
                !(frm.doc.r22_team_assignments||[]).length) {
            marina_load_mood_board_team(frm,frm.doc.mood_board);
        }
    },
    refresh(frm) {
        marina_refresh_creation_date(frm);
        if (!frm.is_new()) {
            const design=frm.doc.name;
            frm.__marina_design_buttons={};
            frm.__marina_menu_version=(frm.__marina_menu_version||0)+1;
            // Plan eligibility is controlled by the milestone Assign
            // permission, not necessarily Design Code Write permission.
            // The server overview removes this shortcut when ineligible.
            marina_design_button(frm,"Create Milestones",()=>{
                if(frm.is_dirty()){
                    frappe.msgprint(__("Save Design Code changes before creating milestones."));
                    return;
                }
                frappe.call({
                    method:"marina_custom_apps.design_management.clean_milestones.api.overview",
                    args:{design_code:design}
                }).then(({message:status})=>{
                    if(frm.doc.name!==design)return;
                    if(!status?.can_plan){
                        frappe.msgprint(__("A milestone plan already exists, or you are not authorized to create it."));
                        return;
                    }
                    frappe.set_route("design-followup-grid",design,
                        "create-milestones",String(Date.now()));
                });
            },"Actions");
            marina_design_button(frm,"Milestone Follow up",()=>
                frappe.set_route("design-followup-grid",design),"Actions");
            const generation=frm.__marina_menu_version;
            frappe.call({
                method:"marina_custom_apps.design_management.clean_milestones.clear_related.can_clear_related_milestones",
                args:{design_code:design}
            }).then(({message:allowed})=>{
                if(!allowed || frm.doc.name!==design ||
                        frm.__marina_menu_version!==generation)return;
                marina_design_button(frm,"Clear Related Milestones",()=>
                    marina_open_clear_milestones_dialog(frm,design),"Actions");
            }).catch(error=>{
                console.warn("Marina Design: milestone reset permission check failed",error);
            });
            marina_add_design_responsibility_button(frm);
            // Frappe List supports a child-table dotted field filter.
            // Parent document read permissions continue to apply.
            if(typeof frappe.model?.can_read!=="function" ||
                    frappe.model.can_read("Design Document")){
                marina_design_button(frm,"Show Linked Documents",()=>{
                    if(frm.is_dirty()){
                        frappe.msgprint(__("Save or discard changes before opening linked documents."));
                        return;
                    }
                    frappe.set_route("List","Design Document","List",
                        {"Design Document Assignment.design_code":design});
                },"Document");
            }
        }
        marina_clean_render_milestones(frm);
        marina_r8_render_overview(frm);
        marina_display_related_documents(frm);
        marina_r9_load_item_statuses(frm);
        marina_render_production_summary(frm);
        marina_r5_load_factory_choices(frm);
        if(!frm.is_new()){
            const currentDesign=frm.doc.name;
            frappe.call({
                method:"marina_custom_apps.marina_design_management.doctype.design_cost_breakdown.design_cost_breakdown.accessible_design_cost",
                args:{design_code:currentDesign}
            }).then(({message:allowed})=>{
                if(!allowed || frm.doc.name!==currentDesign)return;
                frm.add_custom_button(__("Cost Breakdowns"),()=>{
                    frappe.set_route("List","Design Cost Breakdown",
                        {design_code:currentDesign});
                },__("Production"));
            }).catch(error=>console.warn("Cost Breakdown access check failed",error));
        }
        // The shared Marina username form handler performs one scoped lookup.
        // A new Design Code may be fully prepared, including sizes, before its first save.
        const may_edit = frm.is_new() || (typeof frm.has_perm === "function"
            ? frm.has_perm("write") : Boolean(frm.perm && frm.perm[0] && frm.perm[0].write));
        if (may_edit) {
            frm.add_custom_button(__("Choose Sizes"),()=>
                marina_r4_choose_sizes(frm),__("Production"));
            marina_r7_add_item_creation_button(frm);
            frm.add_custom_button(__("Add Production Item"), () => {
                const row=frm.add_child("production_items");
                row.production_key=marina_production_key();
                row.currency=frm.doc.production_currency;
                frm.refresh_field("production_items");
                frappe.show_alert({
                    message:__("New row added. Enter the planned Item Code and use Edit Sizes."),
                    indicator:"blue"
                });
            }, __("Production"));
            frm.add_custom_button(__("Edit Size Breakdown"), () => {
                const choices=(frm.doc.production_items||[]).filter(r=>r.item_code);
                if (!choices.length) {
                    frappe.msgprint(__("Add a Production Item and enter its Item Code first."));
                    return;
                }
                const choices_text=choices.map(r=>r.item_code).join("\n");
                const dialog=new frappe.ui.Dialog({
                    title:__("Select Production Item"),
                    fields:[{
                        fieldname:"code",label:__("Planned Item Code"),
                        fieldtype:"Select",options:choices_text,reqd:1
                    }],
                    primary_action_label:__("Edit Sizes"),
                    primary_action(values) {
                        const row=choices.find(r=>r.item_code===values.code);
                        dialog.hide();
                        marina_edit_production_sizes(frm,row);
                    }
                });
                dialog.show();
                dialog.set_value("code",choices[0].item_code);
            }, __("Production"));
        }
    },
    category(frm) {frm.set_value("subcategory",null);},
    mood_board(frm) {
        const board=frm.doc.mood_board;
        if (!board)return;
        frappe.db.get_value("Mood Board",board,
            ["year","season","collection","drop","display_date"]).then(({message})=>{
            if (!message || board!==frm.doc.mood_board)return;
            ["year","season","collection","drop"].forEach(name=>
                frm.set_value(name,message[name]));
            if (frm.is_new())frm.set_value("display_date",message.display_date);
        });
        if (frm.is_new())marina_load_mood_board_team(frm,board);
    },
    production_currency(frm) {
        (frm.doc.production_items||[]).forEach(row=>{
            frappe.model.set_value(row.doctype,row.name,"currency",frm.doc.production_currency);
        });
        marina_recalculate_production_summary(frm);
    },
    development_stage(frm) {
        if (frm.doc.development_stage==="In Production"
            && !(frm.doc.production_items||[]).length) {
            frappe.msgprint(__("Production Items, unit costs and size quantities are required before saving as In Production."));
        }
    },
    before_save(frm) {
        // Deleting a production item also removes its supporting size allocation
        // rows; it does NOT touch an ERPNext Item.
        const valid=new Set((frm.doc.production_items||[]).map(row=>{
            if (!row.production_key)row.production_key=marina_production_key();
            return row.production_key;
        }));
        frm.doc.production_size_breakdown=(frm.doc.production_size_breakdown||[])
            .filter(row=>valid.has(row.production_key));
        marina_recalculate_production_summary(frm);
    }
});

frappe.ui.form.on("Design Production Item",{
    production_items_add(frm,cdt,cdn) {
        const row=locals[cdt][cdn];
        row.production_key=marina_production_key();
        row.currency=frm.doc.production_currency;
        frm.refresh_field("production_items");
    },
    production_items_remove(frm) {
        // Orphaned allocation rows are pruned on before_save.
        marina_recalculate_production_summary(frm);
    },
    edit_sizes(frm,cdt,cdn) {
        marina_edit_production_sizes(frm,locals[cdt][cdn]);
    },
    unit_cost(frm,cdt,cdn) {
        const row=locals[cdt][cdn];
        frappe.model.set_value(cdt,cdn,"total_cost",
            marina_money((Number(row.unit_cost)||0)*(Number(row.quantity)||0)));
        marina_recalculate_production_summary(frm);
    }
});

function marina_production_key() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID().replace(/-/g,"");
    }
    // Used only by older browsers; server validates uniqueness and shape.
    let value="";
    for(let i=0;i<32;i++) value+="0123456789abcdef"[Math.floor(Math.random()*16)];
    return value;
}

function marina_money(value) {
    return Math.round(((Number(value)||0)+Number.EPSILON)*100)/100;
}

function marina_recalculate_production_summary(frm) {
    const byKey={};
    (frm.doc.production_size_breakdown||[]).forEach(row=>{
        byKey[row.production_key]=(byKey[row.production_key]||0)+(Number(row.qty)||0);
    });
    let qty=0,cost=0;
    (frm.doc.production_items||[]).forEach(item=>{
        item.quantity=byKey[item.production_key]||0;
        item.total_cost=marina_money(item.quantity*(Number(item.unit_cost)||0));
        item.currency=frm.doc.production_currency;
        qty+=item.quantity;
        cost+=item.total_cost;
    });
    frm.doc.production_total_qty=qty;
    frm.doc.production_total_cost=marina_money(cost);
    frm.refresh_field("production_items");
    frm.refresh_field("production_total_qty");
    frm.refresh_field("production_total_cost");
    marina_render_production_summary(frm);
}

function marina_edit_production_sizes(frm,item) {
    if (!item) return;
    const sizeList=(frm.doc.sizes||[]).map(row=>row.size).filter(Boolean);
    if (!sizeList.length) {
        frappe.msgprint(__("Select Sizes on the Design Code before allocating quantities."));
        return;
    }
    if (!item.production_key)item.production_key=marina_production_key();
    const key=item.production_key;
    const current={};
    (frm.doc.production_size_breakdown||[])
        .filter(row=>row.production_key===key)
        .forEach(row=>{current[row.size]=Number(row.qty)||0;});

    const dialog=new frappe.ui.Dialog({
        title:__("Size Breakdown — {0}",[item.item_code || __("New Production Item")]),
        size:"large",
        fields:[{
            fieldname:"size_grid",label:__("Sizes"),fieldtype:"HTML"
        }],
        primary_action_label:__("Apply Size Quantities"),
        primary_action() {
            const newEntries=[];
            let total=0,valid=true;
            dialog.fields_dict.size_grid.$wrapper
                .find("input[data-size-index]").each(function() {
                    const index=Number(this.dataset.sizeIndex);
                    const qty=Number(this.value);
                    if (!Number.isSafeInteger(qty) || qty<0) {
                        valid=false;return;
                    }
                    total+=qty;
                    if(qty>0)newEntries.push({size:sizeList[index],qty});
                });
            if (!valid || !Number.isSafeInteger(total)) {
                frappe.msgprint(__("Size quantities must be nonnegative whole numbers."));
                return;
            }
            frm.doc.production_size_breakdown=(frm.doc.production_size_breakdown||[])
                .filter(row=>row.production_key!==key);
            newEntries.forEach(entry=>{
                const alloc=frm.add_child("production_size_breakdown");
                alloc.production_key=key;
                alloc.size=entry.size;
                alloc.qty=entry.qty;
            });
            frm.refresh_field("production_size_breakdown");
            marina_recalculate_production_summary(frm);
            frm.dirty();
            dialog.hide();
        }
    });
    dialog.show();
    const esc=frappe.utils.escape_html;
    const html='<div class="table-responsive"><table class="table table-bordered"><thead><tr>'+
        '<th>'+__("Size")+'</th><th>'+__("Production Qty")+'</th></tr></thead><tbody>'+
        sizeList.map((size,index)=>'<tr><td>'+esc(size)+'</td><td>'+
            '<input class="form-control" type="number" min="0" step="1" '+
            'data-size-index="'+index+'" value="'+(current[size]||0)+'"/></td></tr>'
        ).join("")+'</tbody></table></div>'+
        '<p class="text-muted">'+__("Only nonzero allocations are stored. Changes take effect when you save the Design Code.")+'</p>';
    dialog.fields_dict.size_grid.$wrapper.html(html);
}

function marina_render_production_summary(frm) {
    const wrapper=frm.fields_dict.production_size_overview?.$wrapper;
    if (!wrapper)return;
    const items=frm.doc.production_items||[];
    if(!items.length) {
        wrapper.html('<p class="text-muted">'+__("No Production Items planned yet.")+'</p>');
        return;
    }
    const esc=frappe.utils.escape_html;
    const sizes=frm.doc.production_size_breakdown||[];
    const statuses=frm.__marina_item_creation_statuses||{};
    const html=items.map(item=>{
        const cells=sizes.filter(row=>row.production_key===item.production_key && Number(row.qty)>0)
            .map(row=>esc(row.size)+": "+esc(String(row.qty))).join(" · ");
        const stat=statuses[item.production_key];
        const status=stat?.status||(frm.__marina_item_status_failed?__("Unavailable"):__("Checking..."));
        const statusClass=status==="Created"?"green":
            status==="Partially Created"?"orange":"gray";
        const tooltip=stat?stat.created_variants+" / "+stat.expected_variants+" "+__("Size Variants Created"):"";
        return '<tr><td>'+esc(item.item_code||__("New Item"))+'</td>'+
            '<td><span class="indicator '+statusClass+'" title="'+esc(tooltip)+'">'+
            esc(__(status))+'</span></td>'+
            '<td>'+esc(item.color_name||"")+'</td><td>'+esc(cells||"—")+'</td>'+
            '<td class="text-right">'+esc(String(item.quantity||0))+'</td>'+
            '<td class="text-right">'+esc(String(marina_money(item.total_cost||0)))+'</td></tr>';
    }).join("");
    wrapper.html('<div class="table-responsive"><table class="table table-bordered">'+
        '<thead><tr><th>'+__("Planned Item Code")+'</th><th>'+__("ERP Item Status")+'</th><th>'+__("Color")+
        '</th><th>'+__("Size Breakdown")+'</th><th>'+__("Qty")+'</th><th>'+
        __("Total Direct Cost")+'</th></tr></thead><tbody>'+html+
        '</tbody></table></div><p><b>'+__("Total Qty")+': '+
        esc(String(frm.doc.production_total_qty||0))+' | '+__("Total Direct Cost")+
        ': '+esc(String(frm.doc.production_total_cost||0))+' '+
        esc(frm.doc.production_currency||"")+'</b></p>');
}

function marina_display_related_documents(frm) {
    const wrapper=frm.fields_dict.related_documents?.$wrapper;
    if (!wrapper)return;
    if(frm.is_new()) {
        wrapper.html('<p class="text-muted">'+__("Save this Design Code to view assigned documents.")+'</p>');
        return;
    }
    frappe.call({
        method:"marina_custom_apps.design_management.api.design_documents.related_documents",
        args:{design_code:frm.doc.name},
        callback({message}) {
            const esc=frappe.utils.escape_html;
            const rows=(message||[]).map(doc=>{
                const files=[
                    ...(doc.attachment ? [{file:doc.attachment,description:__("Primary File")}] : []),
                    ...(doc.additional_files||[])
                ];
                const links=files.filter(item=>item.file && (item.file.startsWith("/files/") || item.file.startsWith("/private/files/")))
                    
                    .map(item=>'<div><a href="'+esc(item.file)+'" target="_blank" rel="noopener">'+
                        esc(item.description||item.designer||__("Open File"))+'</a></div>').join("");
                return '<tr><td><a href="/app/design-document/'+encodeURIComponent(doc.name)+'">'+
                    esc(doc.document_title)+'</a></td><td>'+esc(doc.document_type)+
                    '</td><td>'+esc(doc.superseded_by ? __("Superseded") :
                        (doc.publication_status||"—"))+
                    '</td><td>'+esc(doc.target_milestone_type||"—")+
                    '</td><td>'+ (links||"—") +'</td><td>'+
                    esc(doc.added_username||__("Username not configured"))+'</td></tr>';
            }).join("");
            wrapper.html(rows?
                '<div class="table-responsive"><table class="table table-bordered">'+
                '<thead><tr><th>'+__("Document")+'</th><th>'+__("Type")+
                '</th><th>'+__("Publication")+'</th><th>'+__("Target Milestone")+
                '</th><th>'+__("File")+'</th><th>'+__("Added By")+
                '</th></tr></thead><tbody>'+rows+'</tbody></table></div>':
                '<p class="text-muted">'+__("No documents assigned to this Design Code.")+'</p>');
        }
    });
}


/* Release 4: Pantone thumbnails and ERPNext Size abbreviations. */
frappe.ui.form.on("Marina Design Pantone",{
    pantone(frm,cdt,cdn){
        const row=locals[cdt][cdn];
        if(!row.pantone){
            frappe.model.set_value(cdt,cdn,"color_image","");
            return;
        }
        const selected=row.pantone;
        frappe.call({
            method:"marina_custom_apps.design_management.api.pantone.color_swatch",
            args:{pantone:selected}
        }).then(({message})=>{
            if(locals[cdt][cdn]?.pantone!==selected)return;
            frappe.model.set_value(cdt,cdn,"color_image",message?.color_image||"");
            frm.refresh_field("pantone_components");
        });
    }
});

function marina_r4_choose_sizes(frm){
    frappe.call({
        method:"marina_custom_apps.design_management.api.size_selection.list_size_abbreviations",
        args:{limit:300}
    }).then(({message})=>{
        const options=message||[];
        if(!options.length){
            frappe.msgprint(__("ERPNext Item Attribute Size has no abbreviations."));
            return;
        }
        const existing=new Set((frm.doc.sizes||[]).map(x=>x.size));
        const dlg=new frappe.ui.Dialog({
            title:__("Choose ERPNext Sizes"),
            size:"large",
            fields:[{fieldname:"size_picker",fieldtype:"HTML"}],
            primary_action_label:__("Add Selected Sizes"),
            primary_action(){
                dlg.fields_dict.size_picker.$wrapper.find("input[data-size-index]:checked")
                    .each((_,input)=>{
                        const entry=options[Number(input.dataset.sizeIndex)];
                        if(existing.has(entry.abbr))return;
                        const child=frm.add_child("sizes");
                        child.size=entry.abbr;child.size_description=entry.description;
                        existing.add(entry.abbr);
                    });
                frm.refresh_field("sizes");
                dlg.hide();
            }
        });
        dlg.show();
        const esc=frappe.utils.escape_html;
        dlg.fields_dict.size_picker.$wrapper.html(
            '<input class="form-control mb-2 mdm-size-search" type="search" placeholder="'+
            __("Search size or abbreviation")+'">'+
            '<div style="max-height:370px;overflow:auto">'+options.map((entry,index)=>
                '<label class="d-block border-bottom p-2 mdm-size-choice"><input type="checkbox" data-size-index="'+
                index+'" '+(existing.has(entry.abbr)?'checked disabled':'')+'> <b>'+
                esc(entry.abbr)+'</b> — '+esc(entry.description)+'</label>').join("")+'</div>'
        );
        dlg.fields_dict.size_picker.$wrapper.find(".mdm-size-search").on("input",function(){
            const search=this.value.toLowerCase();
            dlg.fields_dict.size_picker.$wrapper.find(".mdm-size-choice").each(function(){
                $(this).toggle($(this).text().toLowerCase().includes(search));
            });
        });
    });
}
frappe.ui.form.on("Marina Design Size", {
    size(frm, cdt, cdn) {
        const row = locals[cdt]?.[cdn];
        if (!row) return;
        const selected = row.size;
        if (!selected) {
            frappe.model.set_value(cdt, cdn, "size_description", "");
            return;
        }
        frappe.db.get_value("Design Size Reference", selected, "description")
            .then(({message}) => {
                if (locals[cdt]?.[cdn]?.size !== selected) return;
                frappe.model.set_value(cdt, cdn, "size_description", message?.description || "");
            });
    }
});

/* Factory master: active records only for new assignments. */
function marina_r5_load_factory_choices(frm) {
    frm.set_query("factory", () => ({filters: {is_active: 1}}));
}


/* Release 5.5: Marina-only User.username, stable email IDs and one DB lookup.
   Frappe already supports display titles for Link/User; re-use its existing
   renderer and title cache, rather than altering ERPNext User master or roles.
   The server only returns names belonging to the authorized Design Code. */
function marina_r7_add_item_creation_button(frm) {
    if (frm.is_new() || frm.is_dirty()) return;
    if (typeof frm.has_perm === "function" && !frm.has_perm("write")) return;
    if (typeof frappe.model?.can_create === "function" && !frappe.model.can_create("Item")) return;

    frm.add_custom_button(__("Create ERP Item"), () => {
        const rows = (frm.doc.production_items || []).filter(r => r.item_code && r.production_key);
        if (!rows.length) {
            frappe.msgprint(__("Save a Production Item with its Size breakdown first."));
            return;
        }
        const select = new frappe.ui.Dialog({
            title: __("Select Production Item"),
            fields: [{fieldname:"production_key", label:__("Production Item"),
                fieldtype:"Select", reqd:1,
                options: rows.map(r => ({label:r.item_code,value:r.production_key}))}],
            primary_action_label: __("Preview Items"),
            primary_action: async values => {
                if (!values?.production_key) return;
                let response;
                try {
                    response = await frappe.call({
                        method: "marina_custom_apps.design_management.item_creation.preview_item_creation",
                        args: {design_code:frm.doc.name,production_key:values.production_key}
                    });
                } catch (error) { return; }
                const preview = response.message;
                if (!preview?.confirmation_token) return;
                select.hide();
                const escape = value => frappe.utils.escape_html(String(value ?? ""));
                const variants = preview.sizes.map(row =>
                    `<tr><td>${escape(row.abbr)}</td><td>${escape(row.item_code)}</td><td>${escape(row.barcode)}</td><td>${escape(row.qty)}</td></tr>`
                ).join("");
                const mapped = ["Template","Variant"].flatMap(scope =>
                    Object.entries(preview.mapped?.[scope] || {}).map(([name,value]) =>
                        `<tr><td>${escape(scope)}</td><td>${escape(name)}</td><td>${escape(value)}</td></tr>`)
                ).join("");
                const dialog = new frappe.ui.Dialog({
                    title: __("Confirm one-time Item creation"),
                    fields: [{fieldname:"preview", fieldtype:"HTML"}],
                    primary_action_label: __("Create Items"),
                    primary_action: async () => {
                        dialog.get_primary_btn().prop("disabled", true);
                        try {
                            const result = await frappe.call({
                                method: "marina_custom_apps.design_management.item_creation.confirm_item_creation",
                                type: "POST",
                                args: {design_code:frm.doc.name,production_key:values.production_key,
                                       confirmation_token:preview.confirmation_token}
                            });
                            dialog.hide();
                            frappe.msgprint(__("Created Item Template {0} and {1} Size Variants",
                                [result.message.template,result.message.variants.length]));
                            await frm.reload_doc();
                        } finally {
                            dialog.get_primary_btn().prop("disabled", false);
                        }
                    }
                });
                dialog.fields_dict.preview.$wrapper.html(
                    `<p><strong>${__("Item Template")}:</strong> ${escape(preview.template_code)}</p>` +
                    `<p>${__("Item Group")}: ${escape(preview.item_group)} / ${__("Stock UOM")}: ${escape(preview.stock_uom)}</p>` +
                    `<table class="table table-bordered"><thead><tr><th>${__("Size")}</th><th>${__("Variant Code")}</th><th>${__("Barcode")}</th><th>${__("Qty (planning only)")}</th></tr></thead><tbody>${variants}</tbody></table>` +
                    `<h5>${__("Mapped Fields")}</h5><table class="table table-bordered"><thead><tr><th>${__("Applies To")}</th><th>${__("Item Field")}</th><th>${__("Value")}</th></tr></thead><tbody>${mapped}</tbody></table>` +
                    `<p class="text-muted">${__("One-time Item creation. No stock or valuation entry is created.")}</p>`
                );
                dialog.show();
            }
        });
        select.show();
    }, __("Production"));
}

/* Release 7: operator-reviewed Item Name repair, never run on migration. */
/* Release 8: computed only from loaded Design Code fields; no extra queries. */
function marina_r8_render_overview(frm) {
    const w=frm.fields_dict.overview_summary?.$wrapper;
    if(!w)return;
    const e=v=>frappe.utils.escape_html(String(v??""));
    w.html('<div class="row"><div class="col-sm-6"><strong>'+__("Production Qty")+'</strong><div>'+
        e(frm.doc.production_total_qty||0)+'</div></div><div class="col-sm-6"><strong>'+
        __("Direct Cost")+'</strong><div>'+e(frm.doc.production_total_cost||0)+' '+
        e(frm.doc.production_currency||"")+'</div></div></div>');
}
function marina_r9_load_item_statuses(frm) {
    if (frm.is_new()) return;
    const name=frm.doc.name;
    const request=(frm.__marina_item_status_request||0)+1;
    frm.__marina_item_status_request=request;
    frappe.call({
        method:"marina_custom_apps.design_management.item_creation.get_production_item_statuses",
        args:{design_code:name}
    }).then(({message})=>{
        if (frm.doc.name!==name || frm.__marina_item_status_request!==request)return;
        frm.__marina_item_creation_statuses=Object.fromEntries(
            (message||[]).map(row=>[row.production_key,row]));
        marina_render_production_summary(frm);
    }).catch(()=>{
        // Do not misrepresent a failed existence check as Not Created.
        if (frm.__marina_item_status_request!==request)return;
        frm.__marina_item_creation_statuses={};
        frm.__marina_item_status_failed=true;
        marina_render_production_summary(frm);
    });
}


/* Team Head assignment action, placed after Return to Milestone. */
function marina_add_design_responsibility_button(frm){
    if(frm.is_new())return;
    marina_design_button(frm,"Edit Design Responsibility",()=>{
        frm.scroll_to_field("r22_team_assignments");
        frappe.show_alert({
            message:__("Role-to-user assignments are edited here by authorized managers."),
            indicator:"blue"
        });
    },"Actions");
}
frappe.ui.form.on("Design Code", {
    refresh(frm) {
        if (frm.is_new()) return;
        const design_name = frm.doc.name;
        const generation=frm.__marina_menu_version;
        frappe.call({
            method: "marina_custom_apps.design_management.design_deletion.can_delete_design",
            args: {design_code: design_name}
        }).then(({message: allowed}) => {
            if (!allowed || frm.doc.name !== design_name ||
                    frm.__marina_menu_version!==generation)return;
            marina_design_button(frm,"Delete Design", () => {
            if (frm.is_dirty()) {
                frappe.msgprint(__("Save or discard your changes before deleting the Design."));
                return;
            }
            const design = frm.doc.name;
            frappe.call({
                method: "marina_custom_apps.design_management.design_deletion.preview_delete_design",
                args: {design_code: design},
                freeze: true
            }).then(({message: impact}) => {
                if (!impact || frm.doc.name !== design) return;
                const esc = frappe.utils.escape_html;
                const warning =
                    '<p><b>' + __("Delete Design Code {0}?", [esc(design)]) + '</b></p>' +
                    '<p>' + __("The following records will be deleted together:") + '</p>' +
                    '<ul>' +
                    '<li>' + __("Milestones: {0}", [Number(impact.milestones) || 0]) + '</li>' +
                    '<li>' + __("Completed milestones: {0}", [Number(impact.completed_milestones) || 0]) + '</li>' +
                    '<li>' + __("Milestones with QC/Fitting decisions: {0}", [Number(impact.reviewed_milestones) || 0]) + '</li>' +
                    '</ul>' +
                    '<p>' + __("Related document assignments to remove: {0}",
                        [Number(impact.related_documents) || 0]) + '</p>' +
                    '<p><b>' + __("Published files will remain available. A deletion history will be retained.") + '</b></p>' +
                    '<p class="text-danger">' + __("This action cannot be undone from this screen.") + '</p>';
                frappe.confirm(warning, () => {
                    frappe.call({
                        method: "marina_custom_apps.design_management.design_deletion.delete_design",
                        type: "POST",
                        args: {
                            design_code: design,
                            confirm_design_code: design,
                            reason: "Deleted after user confirmation"
                        },
                        freeze: true,
                        freeze_message: __("Deleting Design and linked milestones…")
                    }).then(({message}) => {
                        if (message?.deleted !== design) return;
                        frappe.show_alert({
                            message: __("Design Code deleted successfully."),
                            indicator: "green"
                        });
                        frappe.set_route("List", "Design Code");
                    });
                });
            });
            }, "Actions");
        }).catch(error=>{
            console.warn("Marina Design: Delete action permission check failed",error);
        });
    }
});


/* Return to Milestone: repair an accidental workflow progression without
   deleting plans, execution IDs, published documents, or custody history. */
frappe.ui.form.on("Design Code", {
    refresh(frm) {
        if (frm.is_new()) return;
        const design = frm.doc.name;
        const generation=frm.__marina_menu_version;
        frappe.call({
            method: "marina_custom_apps.design_management.clean_milestones.return_to_milestone.can_open_return_action",
            args: {design_code: design}
        }).then(({message: allowed}) => {
            if (!allowed || frm.doc.name !== design ||
                    frm.__marina_menu_version!==generation)return;
            marina_design_button(frm,"Return to Milestone", () => {
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save or discard changes before returning to a milestone."));
                    return;
                }
                frappe.call({
                    method: "marina_custom_apps.design_management.clean_milestones.return_to_milestone.return_options",
                    args: {design_code: design}
                }).then(({message: options}) => {
                    if (frm.doc.name !== design) return;
                    if (!options?.length) {
                        frappe.msgprint(__("No activated milestones are available for return."));
                        return;
                    }
                    const byName = new Map(options.map(r => [r.milestone_type, r]));
                    const dlg = new frappe.ui.Dialog({
                        title: __("Return Design to Milestone"),
                        size: "large",
                        fields: [
                            {fieldname:"milestone_type", label:__("Milestone"),
                             fieldtype:"Select", options:options.map(x=>x.milestone_type).join("\n"),
                             default:options[0].milestone_type,reqd:1},
                            {fieldname:"step", label:__("Return to Step"),
                             fieldtype:"Select",
                             options:(options[0].steps||[]).map(x=>x.step).join("\n"),
                             default:options[0].steps?.[0]?.step||"",reqd:1},
                            {fieldname:"custody", label:__("Custody After Return"),
                             fieldtype:"Data", read_only:1},
                            {fieldname:"reason", label:__("Reason for Return"),
                             fieldtype:"Small Text", reqd:1,
                             description:__("Enter 10–500 characters; retained in workflow history.")},
                            {fieldname:"impact", fieldtype:"HTML"}
                        ],
                        primary_action_label:__("Confirm Return"),
                        primary_action(values) {
                            if (!preview || preview.milestone_type !== values.milestone_type
                                    || preview.to_step !== values.step) {
                                frappe.msgprint(__("Review the milestone impact before confirming."));
                                return;
                            }
                            const reason=(values.reason||"").trim();
                            if (reason.length<10 || reason.length>500) {
                                frappe.msgprint(__("Provide a return reason (10–500 characters)."));
                                return;
                            }
                            const esc=frappe.utils.escape_html;
                            const warning=__("Return {0} to {1}?", [
                                esc(preview.milestone_type),esc(preview.to_step)]) + " " +
                                __("This will move {0} subsequent milestones to Future. Historical evidence will be retained.",[
                                    preview.to_future.length]);
                            frappe.confirm(warning, () => {
                                frappe.call({
                                    method:"marina_custom_apps.design_management.clean_milestones.return_to_milestone.execute_return",
                                    type:"POST", freeze:true,
                                    args:{
                                        design_code:design,
                                        milestone_type:values.milestone_type,
                                        step:values.step,reason,
                                        expected_revision:preview.revision
                                    }
                                }).then(({message})=>{
                                    dlg.hide();
                                    frappe.show_alert({
                                        indicator:"green",
                                        message:__("Returned to {0}; {1} milestones moved to Future.",[
                                            message?.returned||values.milestone_type,
                                            message?.moved_to_future||0])
                                    });
                                    frm.reload_doc();
                                });
                            });
                        }
                    });
                    let preview=null, version=0, selectionVersion=0;
                    let updatingSteps=false, initializing=true;
                    const setConfirmEnabled=(enabled)=>{
                        const button=dlg.get_primary_btn?.();
                        if (button?.prop)button.prop("disabled",!enabled);
                    };
                    const showImpact=(markup)=>{
                        dlg.fields_dict.impact.$wrapper.html(markup);
                    };
                    const renderPreview=async()=>{
                        const current=++version;
                        preview=null;
                        setConfirmEnabled(false);
                        const milestone=dlg.get_value("milestone_type");
                        const step=dlg.get_value("step");
                        dlg.set_value("custody","");
                        if (!milestone || !step) {
                            showImpact('<p class="text-muted">'+
                                __("Select a milestone and return step to review the impact.")+'</p>');
                            return;
                        }
                        showImpact('<p class="text-muted">'+
                            __("Checking milestone impact...")+'</p>');
                        try {
                            const {message:result}=await frappe.call({
                                method:"marina_custom_apps.design_management.clean_milestones.return_to_milestone.preview_return",
                                args:{design_code:design,milestone_type:milestone,step}
                            });
                            if (version!==current || frm.doc.name!==design) return;
                            if (!result?.revision)throw new Error("Missing preview revision");
                            preview=result;
                            await dlg.set_value("custody",
                                (result.custodian_title||result.custodian||"") +
                                " (" + result.custody_role + ")");
                            if (version!==current)return;
                            const esc=frappe.utils.escape_html;
                            const moved=(result.to_future||[]).map(r=>
                                '<li>'+esc(r.milestone_type)+" — "+
                                esc(r.was)+" / "+esc(r.step)+" → "+__("Future")+"</li>").join("");
                            showImpact(
                                '<div class="mt-3"><b>'+__("Impact Preview")+'</b>'+
                                '<p>'+__("Current Step")+": "+esc(result.from_step)+
                                " → "+esc(result.to_step)+'</p>'+
                                '<p>'+__("Other milestones moved to Future: {0}",[
                                    result.to_future.length])+'</p>'+
                                (moved?'<ul style="max-height:170px;overflow:auto">'+moved+'</ul>':
                                    '<p class="text-muted">'+__("No subsequent active milestones.")+'</p>')+
                                '<p class="text-muted">'+
                                __("Published documents and historical custody records will remain unchanged.")+
                                '</p></div>');
                            setConfirmEnabled(true);
                        } catch(error) {
                            if (version!==current || frm.doc.name!==design)return;
                            preview=null;
                            setConfirmEnabled(false);
                            // Never strand the user at a spinner. Frappe also
                            // shows its own server exception dialog if present.
                            showImpact('<p class="text-danger">'+
                                __("Unable to preview this return. Check milestone dependencies and the assigned custody role, then retry.")+
                                '</p><button type="button" class="btn btn-default btn-sm mdm-retry-return">'+
                                __("Retry Preview")+'</button>');
                            dlg.fields_dict.impact.$wrapper
                                .find(".mdm-retry-return")
                                .on("click",()=>{void renderPreview();});
                        }
                    };
                    const updateSteps=async()=>{
                        const ticket=++selectionVersion;
                        const selected=byName.get(dlg.get_value("milestone_type"));
                        const steps=selected?.steps||[];
                        ++version; // invalidate any in-flight preview
                        preview=null;
                        setConfirmEnabled(false);
                        showImpact('<p class="text-muted">'+
                            __("Preparing milestone steps...")+'</p>');
                        updatingSteps=true;
                        try {
                            dlg.set_df_property("step","options",
                                steps.map(s=>s.step).join("\n"));
                            // Dialog.set_value can be asynchronous: do not read
                            // the selected step or preview until this resolves.
                            await dlg.set_value("step",steps[0]?.step||"");
                        } finally {
                            updatingSteps=false;
                        }
                        if (ticket!==selectionVersion)return;
                        await renderPreview();
                    };
                    dlg.show();
                    setConfirmEnabled(false);
                    dlg.fields_dict.milestone_type.$input.on("change",
                        ()=>{if (!initializing)void updateSteps();});
                    dlg.fields_dict.step.$input.on("change",
                        ()=>{if (!initializing && !updatingSteps)void renderPreview();});
                    // Always await initial control writes. Frappe Select fields
                    // may display a value before Dialog.get_value reflects it.
                    void (async()=>{
                        try {
                            await dlg.set_value("milestone_type",options[0].milestone_type);
                            await updateSteps();
                        } catch(error) {
                            preview=null;
                            setConfirmEnabled(false);
                            showImpact('<p class="text-danger">'+
                                __("Could not initialize the return preview. Close and reopen this dialog.")+
                                '</p>');
                        } finally {
                            initializing=false;
                        }
                    })();
                });
            }, "Actions");
        }).catch(error=>{
            console.warn("Marina Design: Return action permission check failed",error);
        });
    }
});


/* Bidirectional document linking. Design Document Assignment is canonical:
   Link Published Document appends the Design Code to the existing document,
   and the regular Related Documents panel reflects it immediately. */
frappe.ui.form.on("Design Code", {
    refresh(frm) {
        if (frm.is_new()) return; // no stable Design Code ID before first Save
        const design=frm.doc.name;
        const generation=frm.__marina_menu_version;
        frappe.call({
            method:"marina_custom_apps.design_management.api.design_documents.can_link_published_document",
            args:{design_code:design}
        }).then(({message:allowed})=>{
            if (frm.is_new() || frm.doc.name!==design ||
                    frm.__marina_menu_version!==generation)return;
            if (allowed) marina_design_button(frm,"Link To Published Document",()=>{
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save or discard Design Code changes before linking a document."));
                    return;
                }
                let dialog=null;
                let previewRequest=0;
                let lastSelectedDocument="";
                let submitting=false;
                const showDetails=(html)=>{
                    dialog.fields_dict.details.$wrapper.html(html);
                };
                const previewSelected=async()=>{
                    if(!dialog)return;
                    const name=(dialog.get_value("document_name")||"").trim();
                    const ticket=++previewRequest;
                    if(name!==lastSelectedDocument){
                        lastSelectedDocument=name;
                        // A new document must not inherit the previous
                        // document's Target Milestone Type override.
                        await dialog.set_value("target_milestone_type","");
                    }
                    if(ticket!==previewRequest)return;
                    if(!name){
                        showDetails('<p class="text-muted">'+
                            __("Select an existing Published Design Document.")+'</p>');
                        return;
                    }
                    showDetails('<p class="text-muted">'+
                        __("Verifying published document...")+'</p>');
                    try {
                        const {message:info}=await frappe.call({
                            method:"marina_custom_apps.design_management.api.design_documents.published_document_link_details",
                            args:{design_code:design,document_name:name}
                        });
                        if(ticket!==previewRequest || dialog.get_value("document_name")!==name ||
                                frm.doc.name!==design)return;
                        if(!info || info.name!==name)throw new Error("Invalid document details");
                        // Do not overwrite a user-entered milestone override.
                        if(!dialog.get_value("target_milestone_type") &&
                                info.related_milestone_type) {
                            await dialog.set_value("target_milestone_type",
                                info.related_milestone_type);
                        }
                        if(ticket!==previewRequest || dialog.get_value("document_name")!==name)return;
                        const esc=frappe.utils.escape_html;
                        showDetails('<p><b>'+esc(info.document_title||info.name)+'</b>'+
                            ' · '+esc(info.document_type||"")+'</p>'+
                            (info.already_linked?
                                '<p class="text-warning">'+
                                __("This Design Code is already linked to the document.")+'</p>':
                                '<p class="text-muted">'+
                                __("Published document verified. Linking does not require an existing milestone plan or complete any milestone.")+
                                '</p>'));
                    } catch(error) {
                        if(ticket!==previewRequest)return;
                        showDetails('<p class="text-warning">'+
                            __("Preview could not be loaded. You can still press Link Document; the server will check the document and explain any error.")+
                            '</p>');
                    }
                };
                const setBusy=busy=>{
                    const button=dialog?.get_primary_btn?.();
                    if(button?.prop)button.prop("disabled",busy);
                };
                dialog=new frappe.ui.Dialog({
                    title:__("Link Published Design Document"),
                    size:"large",
                    fields:[
                        {
                            fieldname:"document_name",fieldtype:"Link",
                            options:"Design Document",label:__("Published Document"),
                            reqd:1,
                            // Frappe Link selection is model-driven and may not
                            // emit a native jQuery input 'change' event.
                            onchange(){void previewSelected();},
                            get_query:()=>({
                                query:"marina_custom_apps.design_management.api.design_documents.search_linkable_published_documents",
                                filters:{design_code:design}
                            })
                        },
                        {fieldname:"details",fieldtype:"HTML"},
                        {
                            fieldname:"target_milestone_type",
                            label:__("Target Milestone Type (Optional)"),
                            fieldtype:"Link",options:"Design Milestone Type",
                            description:__("Linking does not require the milestone to exist in this Design's plan. Leave blank until configured, or choose an existing milestone for a Design-specific override.")
                        }
                    ],
                    primary_action_label:__("Link Document"),
                    async primary_action(values) {
                        // Do not depend on the optional preview to enable this
                        // action. Revalidate on the server every time it is
                        // pressed, then let the transactional endpoint recheck.
                        if(submitting)return;
                        const name=(values.document_name||"").trim();
                        if(!name){
                            frappe.msgprint(__("Select a Published Design Document."));
                            return;
                        }
                        submitting=true;
                        setBusy(true);
                        try{
                            const {message:info}=await frappe.call({
                                method:"marina_custom_apps.design_management.api.design_documents.published_document_link_details",
                                args:{design_code:design,document_name:name}
                            });
                            if(!info || info.name!==name || frm.doc.name!==design){
                                frappe.msgprint(__("The selected document changed. Please reopen and verify the link."));
                                return;
                            }
                            if(info.already_linked){
                                frappe.msgprint(__("This Design Code is already linked to the selected document."));
                                void previewSelected();
                                return;
                            }
                            // An explicit override is optional. The server
                            // uses the Published document's milestone when
                            // available, without requiring it in this Design's
                            // milestone plan.
                            const milestone=(dialog.get_value("target_milestone_type")||"").trim();
                            const {message:linked}=await frappe.call({
                                method:"marina_custom_apps.design_management.api.design_documents.link_published_document",
                                type:"POST",freeze:true,
                                args:{
                                    design_code:design,
                                    document_name:name,
                                    target_milestone_type:milestone||null
                                }
                            });
                            if(!linked || frm.doc.name!==design)return;
                            dialog.hide();
                            frappe.show_alert({
                                indicator:"green",
                                message:__("Linked {0} to Design {1}.",[linked.document,design])
                            });
                            marina_display_related_documents(frm);
                        } finally {
                            submitting=false;
                            setBusy(false);
                        }
                    }
                });
                dialog.show();
                showDetails('<p class="text-muted">'+
                    __("Select an existing Published Design Document.")+'</p>');
                // Deliberately leave the action enabled. The selection and
                // server permissions are checked when the user presses it.
            },"Document");
        }).catch(error=>{
            console.warn("Marina Design: Published document permission check failed",error);
        });
    }
});
/* New Document is independent of permission to link an existing Published
   Document. A failed Link permission check must never hide this shortcut. */
frappe.ui.form.on("Design Code", {
    refresh(frm) {
        if(frm.is_new())return;
        const design=frm.doc.name;
        const generation=frm.__marina_menu_version;
        // Load permissions before evaluating can_create. Without the
        // DocType metadata this check may incorrectly return false.
        frappe.model.with_doctype("Design Document",()=>{
            if(frm.doc.name!==design || frm.__marina_menu_version!==generation)return;
            if(typeof frappe.model?.can_create==="function" &&
                    !frappe.model.can_create("Design Document"))return;
            marina_design_button(frm,"New Design Document",()=>{
                    if (frm.is_dirty()) {
                        frappe.msgprint(__("Save your Design Code changes before creating its document."));
                        return;
                    }
                    frappe.model.with_doctype("Design Document",()=>{
                        if(frm.doc.name!==design)return;
                        const draft=frappe.model.get_new_doc("Design Document");
                        frappe.model.add_child(draft,
                            "Design Document Assignment","assignments").design_code=design;
                        draft.filter_mood_board=frm.doc.mood_board;
                        frappe.set_route("Form","Design Document",draft.name);
                    });
            },"Document");
        });
    }
});

