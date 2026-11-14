/* Bulk Designer assignment from the standard Design Code List Actions menu.
   Keep the native ERPNext List Delete action unchanged. */
const marina_design_code_previous_list_onload =
    frappe.listview_settings["Design Code"]?.onload;
const marina_design_code_previous_formatters =
    frappe.listview_settings["Design Code"]?.formatters || {};
const marina_design_code_merchandiser_cache=Object.create(null);

// Process large selections in atomic backend requests of at most 20 designs.
// The back end deliberately retains its MAX_BULK_DESIGNS=20 safety limit.
function marina_milestone_creation_batches(names,size=20){
    const batches=[];
    for(let i=0;i<names.length;i+=size)batches.push(names.slice(i,i+size));
    return batches;
}

// Display only User.username, while keeping the real User ID in the
// filterable link. Never change the stored Link or global User title rules.
function marina_design_code_merchandiser_cell(user_id,doc){
    if(!user_id)return '<span class="text-muted">—</span>';
    const esc=frappe.utils.escape_html;
    const cached=marina_design_code_merchandiser_cache[doc.name];
    const title=cached?.user_id===user_id ?
        cached.username : __("Loading username…");
    return '<span class="ellipsis"><a class="filterable ellipsis marina-list-merchandiser"'
        +' data-design-code="'+esc(doc.name)+'"'
        +' data-filter="assigned_merchandiser,=,'+esc(user_id)+'"'
        +' title="'+esc(title)+'">'+esc(title)+'</a></span>';
}

function marina_design_code_refresh_merchandiser_labels(listview){
    const records=(listview.data||[])
        .filter(row=>row.name && row.assigned_merchandiser);
    const names=[...new Set(records.map(row=>row.name))];
    const seq=(listview.__marina_merch_seq||0)+1;
    listview.__marina_merch_seq=seq;
    if(!names.length)return;
    frappe.call({
        method:"marina_custom_apps.design_management.api.user_display.design_code_list_merchandiser_usernames",
        args:{design_codes:names}
    }).then(({message:titles})=>{
        if(listview.__marina_merch_seq!==seq)return;
        const current=new Map((listview.data||[]).map(row=>[
            row.name,row.assigned_merchandiser
        ]));
        records.forEach(row=>{
            if(current.get(row.name)!==row.assigned_merchandiser)return;
            marina_design_code_merchandiser_cache[row.name]={
                user_id:row.assigned_merchandiser,
                username:titles?.[row.name]||__("Username not configured")
            };
        });
        // Only update the Merchandiser column on rows in this List View.
        // Other links, filters and selection checkboxes are untouched.
        listview.$result.find(".marina-list-merchandiser").each(function(){
            const link=$(this);
            const name=link.attr("data-design-code");
            const data=marina_design_code_merchandiser_cache[name];
            if(!data || current.get(name)!==data.user_id)return;
            link.text(data.username).attr("title",data.username);
        });
    }).catch(error=>{
        console.warn("Unable to resolve Design Code merchandiser usernames",error);
        if(listview.__marina_merch_seq!==seq)return;
        listview.$result.find(".marina-list-merchandiser")
            .text(__("Username unavailable"));
    });
}

frappe.listview_settings["Design Code"] = Object.assign(
    frappe.listview_settings["Design Code"] || {}, {
    onload(listview) {
        if(typeof marina_design_code_previous_list_onload==="function"){
            marina_design_code_previous_list_onload(listview);
        }
        const original_refresh=listview.refresh.bind(listview);
        listview.refresh=(...args)=>Promise.resolve(original_refresh(...args))
            .then(result=>{
                marina_design_code_refresh_merchandiser_labels(listview);
                return result;
            });

        // Use controlled milestone transitions, never Frappe's generic bulk field
        // editor: existing Fabric Sourcing plans may change custody and steps.
        listview.page.add_action_item(__("Set Fabric Approval"), async () => {
            const selected=listview.get_checked_items(true);
            if(!selected?.length || selected.length>20){
                frappe.msgprint(__("Select between 1 and 20 Design Codes."));
                return;
            }
            const method="marina_custom_apps.design_management.clean_milestones.bulk_fabric_approval";
            const dialog=new frappe.ui.Dialog({
                title:__("Set Fabric Approval for Selected Designs"),
                fields:[
                    {fieldname:"approval",fieldtype:"Select",label:__("Fabric Approval"),
                     options:"\nRequired\nNot Required",reqd:1},
                    {fieldname:"reason",fieldtype:"Small Text",
                     label:__("Reason for Change"),reqd:1,
                     description:__("Required for audit history, at least 5 characters.")},
                    {fieldname:"preview",fieldtype:"HTML",
                     options:'<p class="text-muted">'+
                        __("Choose a value and press Preview to validate all selected designs.")+'</p>'}
                ],
                primary_action_label:__("Preview"),
                primary_action:async values=>{
                    const btn=dialog.get_primary_btn();
                    btn.prop("disabled",true);
                    try{
                        const approval=values.approval;
                        const reason=(values.reason||"").trim();
                        if(reason.length<5 || reason.length>350){
                            frappe.msgprint(__("Enter a reason between 5 and 350 characters."));
                            return;
                        }
                        const {message:preview}=await frappe.call({
                            method:method+".preview_bulk_fabric_approval",
                            args:{design_codes:selected,approval}
                        });
                        if(!preview || preview.selected!==selected.length)throw new Error("Invalid preview");
                        const esc=frappe.utils.escape_html;
                        const rows=preview.designs.map(item=>
                            '<tr><td>'+esc(item.design_code)+'</td><td>'+
                            esc(item.previous)+'</td><td>'+esc(item.status)+'</td><td>'+
                            esc((item.reasons||[]).join("; ")||"—")+'</td></tr>').join("");
                        dialog.fields_dict.preview.$wrapper.html(
                            '<p>'+esc(__("Ready: {0} (historical classification only: {1}), Unchanged: {2}, Blocked: {3}",[
                                preview.ready,preview.historical||0,preview.unchanged,preview.blocked]))+'</p>'+
                            '<div style="max-height:260px;overflow:auto"><table class="table table-sm table-bordered">'+
                            '<thead><tr><th>Design</th><th>Previous</th><th>Status</th><th>Reason</th></tr></thead>'+
                            '<tbody>'+rows+'</tbody></table></div>');
                        if(preview.blocked || !preview.ready)return;
                        frappe.confirm(
                            __("Set Fabric Approval to {0} for {1} designs? {2} completed milestones will receive historical classification only; unfinished milestones may change custody.",[
                                approval,preview.ready,preview.historical||0]),
                            async()=>{
                                const button=dialog.get_primary_btn();
                                button.prop("disabled",true);
                                try{
                                    const {message:result}=await frappe.call({
                                        method:method+".set_bulk_fabric_approval",
                                        type:"POST",freeze:true,
                                        args:{design_codes:selected,approval,reason,confirm:1}
                                    });
                                    dialog.hide();
                                    listview.clear_checked_items();
                                    listview.refresh();
                                    frappe.msgprint({
                                        title:__("Fabric Approval Updated"),
                                        message:__("Updated {0} designs; unchanged {1}.",[
                                            result.updated,result.unchanged]),
                                        indicator:"green"
                                    });
                                }catch(error){
                                    console.error("Bulk Fabric Approval update failed",error);
                                }finally{button.prop("disabled",false);}
                            }
                        );
                    }catch(error){
                        console.error("Bulk Fabric Approval preview failed",error);
                        frappe.msgprint(__("Unable to validate the selected designs. No changes were made."));
                    }finally{btn.prop("disabled",false);}
                }
            });
            dialog.show();
        });

        listview.page.add_action_item(__("Assign Designer"), () => {
            const selected = listview.get_checked_items(true);
            if(!selected?.length){
                frappe.msgprint(__("Select one or more Design Codes first."));
                return;
            }
            if(selected.length>50){
                frappe.msgprint(__("Select a maximum of 50 Design Codes at a time."));
                return;
            }

            const path="marina_custom_apps.design_management.clean_milestones.bulk_designer";
            frappe.call({
                method:path+".preview_bulk_designer_assignment",
                args:{design_codes:selected}
            }).then(({message:preview})=>{
                if(!preview)return;
                const dialog=new frappe.ui.Dialog({
                    title:__("Assign Designer"),
                    fields:[
                        {
                            fieldname:"summary",fieldtype:"HTML",
                            options:'<div class="text-muted">'+
                                __("Selected: {0} | Unassigned: {1} | Already assigned: {2}",[
                                    preview.total,preview.unassigned,preview.assigned
                                ])+'</div>'
                        },
                        {
                            fieldname:"designer",label:__("Designer"),
                            fieldtype:"Link",options:"User",reqd:1,
                            get_query:()=>({
                                query:"marina_custom_apps.design_management.security.participants.search_participant_users",
                                filters:{module_role:"Designer"}
                            })
                        },
                        {
                            fieldname:"mode",label:__("Existing Assignments"),
                            fieldtype:"Select",reqd:1,
                            options:"Skip Assigned\nReplace Existing",
                            default:"Skip Assigned",
                            onchange(){
                                const mode=dialog.get_value("mode");
                                dialog.set_df_property("reason","hidden",
                                    mode==="Replace Existing"?0:1);
                                dialog.set_df_property("reason","reqd",
                                    mode==="Replace Existing"?1:0);
                            }
                        },
                        {
                            fieldname:"reason",label:__("Reason for Reassignment"),
                            fieldtype:"Small Text",hidden:1,
                            description:__("Required when replacing a current designer; recorded in responsibility and custody history.")
                        }
                    ],
                    primary_action_label:__("Assign Designer"),
                    primary_action(values){
                        const replace=values.mode==="Replace Existing";
                        const reason=(values.reason||"").trim();
                        if(replace && reason.length<10){
                            frappe.msgprint(__("Enter a reassignment reason of at least 10 characters."));
                            return;
                        }
                        const perform=()=>{
                            const btn=dialog.get_primary_btn();
                            btn.prop("disabled",true);
                            frappe.call({
                                method:path+".bulk_assign_designer",
                                args:{
                                    design_codes:selected,
                                    designer:values.designer,
                                    replace_existing:replace?1:0,
                                    confirm_replace:replace?1:0,
                                    reason:replace?reason:""
                                },
                                freeze:true,
                                freeze_message:__("Assigning selected Design Codes")
                            }).then(({message:result})=>{
                                if(!result)return;
                                dialog.hide();
                                listview.clear_checked_items();
                                listview.refresh();
                                frappe.msgprint({
                                    title:__("Designer Assignment Completed"),
                                    message:__("Updated {0} designs; skipped {1}.",[
                                        result.updated,result.skipped
                                    ]),
                                    indicator:"green"
                                });
                            }).finally(()=>btn.prop("disabled",false));
                        };
                        if(replace){
                            frappe.confirm(
                                __("Replace the existing Designer on selected designs? Existing custody changes will be recorded in workflow history."),
                                perform
                            );
                        } else {
                            perform();
                        }
                    }
                });
                dialog.show();
            }).catch(error=>{
                console.warn("Unable to preview bulk Designer assignment",error);
            });
        });

        // One user selection and confirmation; each backend request stays
        // within its existing atomic 20-design transaction and permission checks.
        listview.page.add_action_item(__("Create Milestones"), async () => {
            const selected=listview.get_checked_items(true);
            if(!selected?.length){
                frappe.msgprint(__("Select one or more Design Codes first."));
                return;
            }
            const batches=marina_milestone_creation_batches(selected);
            const endpoint="marina_custom_apps.design_management.clean_milestones.bulk_create";
            const esc=frappe.utils.escape_html;
            let preview=null, creating=false, previewReady=false;
            let failedIndices=[], successful=new Map(), failureReasons=new Map();
            const dialog=new frappe.ui.Dialog({
                title:__("Create Milestones in Bulk"),
                size:"large",
                fields:[
                    {fieldname:"progress",fieldtype:"HTML",
                     options:'<p class="text-muted">'+esc(__("Preparing milestone preview…"))+'</p>'},
                    {fieldname:"preview",fieldtype:"HTML",
                     options:'<p class="text-muted">'+esc(__("Checking selected Design Codes in batches of 20."))+'</p>'},
                    {fieldname:"confirm_creation",fieldtype:"Check",
                     label:__("I confirm creating milestone plans for the ready designs using each Design Code's Creation Date"),
                     default:0}
                ],
                primary_action_label:__("Create Milestones"),
                primary_action(values){
                    if(creating || !previewReady || !preview?.ready)return;
                    if(!values.confirm_creation){
                        frappe.show_alert({
                            message:__("Confirm milestone creation before proceeding."),
                            indicator:"orange"
                        },5);
                        return;
                    }
                    // Retry only the failed batches. Previously successful
                    // batches are never re-sent within this dialog.
                    const pending=failedIndices.length ? [...failedIndices] :
                        batches.map((_,index)=>index).filter(index=>!successful.has(index));
                    if(!pending.length)return;
                    void performBatches(pending);
                }
            });
            dialog.show();
            dialog.get_primary_btn().prop("disabled",true);
            // Do not let the operator dismiss a partially executed transaction
            // while a batch request is still being submitted.
            dialog.$wrapper.on("hide.bs.modal.marinaMilestoneCreate",event=>{
                if(creating)event.preventDefault();
            });
            const progress=(phase,completed,total)=>{
                const percent=total?Math.round(completed*100/total):100;
                dialog.fields_dict.progress.$wrapper.html(
                    '<div class="mb-2" role="status" aria-live="polite">'+
                        esc(phase+" — "+completed+"/"+total)+
                    '</div><div class="progress" style="height:9px">'+
                    '<div class="progress-bar" role="progressbar" aria-valuenow="'+percent+
                    '" aria-valuemin="0" aria-valuemax="100" style="width:'+percent+
                    '%;background:#551C25"></div></div>'
                );
            };
            const renderPreview=()=>{
                const rows=(preview.designs||[]).map(item=>{
                    const readiness=item.status==="ready" ? __("Ready") :
                        item.status==="existing" ? __("Already Created") : __("Blocked");
                    return '<tr><td>'+esc(item.design_code)+'</td>'+
                        '<td>'+esc(item.creation_date||"—")+'</td>'+
                        '<td>'+esc(readiness)+'</td>'+
                        '<td>'+esc((item.reasons||[]).join("; ")||"—")+'</td></tr>';
                }).join("");
                const summary='<p>'+esc(__("Selected: {0} | Ready: {1} | Already Created: {2} | Blocked: {3}",[
                    preview.selected,preview.ready,preview.existing,preview.blocked
                ]))+'</p>'+
                    '<p class="text-muted">'+esc(__("Each eligible Design will use its own Creation Date and all {0} active milestone types with their master lead times.",[
                        preview.milestones_per_design
                    ]))+'</p>'+
                    '<p class="text-muted">'+esc(__("Processing will use {0} sequential batch(es), at most 20 designs per batch.",[batches.length]))+'</p>'+
                    '<div style="max-height:290px;overflow:auto">'+
                    '<table class="table table-bordered table-sm"><thead><tr>'+
                    '<th>'+esc(__("Design Code"))+'</th><th>'+esc(__("Creation Date"))+'</th>'+
                    '<th>'+esc(__("Status"))+'</th><th>'+esc(__("Reason"))+'</th>'+
                    '</tr></thead><tbody>'+rows+'</tbody></table></div>';
                dialog.fields_dict.preview.$wrapper.html(summary);
            };
            const summarizeResults=()=>{
                const done=[...successful.values()];
                const created=done.reduce((n,row)=>n+Number(row.created||0),0);
                const existing=done.reduce((n,row)=>n+Number(row.existing||0),0);
                const blocked=done.reduce((n,row)=>n+Number(row.blocked||0),0);
                const failed=failedIndices.reduce((n,i)=>n+batches[i].length,0);
                const unresolved=(preview?.selected||0)-done.reduce((n,row)=>n+Number(row.selected||0),0)-failed;
                const failedRows=failedIndices.map(i=>
                    '<li><strong>'+esc(__("Batch {0} ({1} designs)",[
                        i+1,batches[i].length
                    ]))+'</strong>: '+esc(batches[i].join(", "))+
                    (failureReasons.has(i) ? '<div class="text-muted">'+
                        esc(failureReasons.get(i))+'</div>' : "")+'</li>'
                ).join("");
                const blockedRows=done.flatMap(row=>(row.designs||[]).filter(d=>d.status==="blocked"))
                    .map(d=>'<li>'+esc(d.design_code+": "+(d.reasons||[]).join("; "))+'</li>')
                    .join("");
                const counts=__("Created: {0} | Already Created: {1} | Blocked: {2} | Failed: {3}",[
                    created,existing,blocked,failed
                ]);
                const summary='<p><strong>'+esc(counts)+'</strong></p>'+
                    (unresolved>0?'<p>'+esc(__("Not processed: {0}",[unresolved]))+'</p>':"")+
                    (failedRows?'<p class="text-danger">'+esc(__("Failed batches can be retried safely; completed batches are not repeated."))+
                        '</p><ul>'+failedRows+'</ul>':"")+
                    (blockedRows?'<p>'+esc(__("Blocked designs (not created):"))+'</p><div style="max-height:190px;overflow:auto"><ul>'+
                        blockedRows+'</ul></div>':"");
                return {created,existing,blocked,failed,summary};
            };
            async function performBatches(indices){
                creating=true;
                dialog.get_primary_btn().prop("disabled",true);
                dialog.$wrapper.find(".modal-header .close").prop("disabled",true);
                failedIndices=[];
                const total=indices.length;
                for(let pos=0;pos<total;pos++){
                    const index=indices[pos];
                    progress(__("Creating milestone batches"),pos,total);
                    try{
                        const {message:result}=await frappe.call({
                            method:endpoint+".bulk_create_milestones",
                            args:{design_codes:batches[index],confirm:1},
                            type:"POST"
                        });
                        if(!result || Number(result.selected)!==batches[index].length ||
                           !Array.isArray(result.designs)){
                            throw new Error("Incomplete response for batch "+(index+1));
                        }
                        successful.set(index,result);
                        failureReasons.delete(index);
                    }catch(error){
                        console.warn("Milestone creation batch "+(index+1)+" failed",error);
                        failedIndices.push(index);
                        failureReasons.set(index,String(error?.message || __("Server request failed; review Error Log.")).slice(0,240));
                    }
                    progress(__("Creating milestone batches"),pos+1,total);
                }
                creating=false;
                dialog.$wrapper.find(".modal-header .close").prop("disabled",false);
                const outcome=summarizeResults();
                if(failedIndices.length){
                    dialog.fields_dict.preview.$wrapper.html(outcome.summary);
                    dialog.get_primary_btn().text(__("Retry Failed Batches"));
                    dialog.get_primary_btn().prop("disabled",false);
                    frappe.show_alert({
                        message:__("Some milestone batches failed. Review the results and retry failed batches."),
                        indicator:"orange"
                    },8);
                    return;
                }
                // Hide first: a second nested confirmation can remain on
                // screen if the success dialog opens before the preview closes.
                dialog.hide();
                listview.clear_checked_items();
                listview.refresh();
                frappe.msgprint({
                    title:__("Bulk Milestone Creation Result"),
                    message:outcome.summary,
                    indicator:outcome.created?"green":"orange"
                });
            }
            // Preview every chunk without raising the single-request backend
            // limit. Master milestone types must remain consistent across
            // previews; creation revalidates all permissions and readiness.
            try{
                const previews=[];
                for(let i=0;i<batches.length;i++){
                    progress(__("Checking milestone prerequisites"),i,batches.length);
                    const {message:part}=await frappe.call({
                        method:endpoint+".preview_bulk_create_milestones",
                        args:{design_codes:batches[i]},type:"POST"
                    });
                    if(!part || Number(part.selected)!==batches[i].length ||
                       !Array.isArray(part.designs) || part.designs.length!==batches[i].length){
                        throw new Error("Incomplete milestone preview for batch "+(i+1));
                    }
                    if(previews.length && JSON.stringify(part.milestone_types)!==
                       JSON.stringify(previews[0].milestone_types)){
                        throw new Error("Active milestone types changed during preview. Refresh and retry.");
                    }
                    previews.push(part);
                    progress(__("Checking milestone prerequisites"),i+1,batches.length);
                }
                const designs=previews.flatMap(part=>part.designs);
                preview={
                    designs,selected:designs.length,
                    ready:designs.filter(item=>item.status==="ready").length,
                    existing:designs.filter(item=>item.status==="existing").length,
                    blocked:designs.filter(item=>item.status==="blocked").length,
                    milestone_types:previews[0].milestone_types,
                    milestones_per_design:previews[0].milestones_per_design
                };
                renderPreview();
                previewReady=true;
                dialog.get_primary_btn().prop("disabled",!preview.ready);
            }catch(error){
                console.warn("Unable to preview bulk milestone creation",error);
                dialog.fields_dict.preview.$wrapper.html(
                    '<p class="text-danger">'+esc(__("Milestone preview failed. No milestone plans were created. Close this dialog and retry."))+'</p>'
                );
                progress(__("Preview interrupted"),0,batches.length);
            }
        });

        frappe.call({
            method:"marina_custom_apps.design_management.clean_milestones.clear_related.can_clear_milestones_action"
        }).then(({message:allowed})=>{
            if(!allowed)return;
            listview.page.add_action_item(__("Clear Related Milestones"),async ()=>{
                const selected=listview.get_checked_items(true);
                if(!selected?.length){
                    frappe.msgprint(__("Select one or more Design Codes first."));
                    return;
                }
                // The backend retains its atomic 20-design limit plus size,
                // audit, permission and revision checks on every request.
                const batches=marina_milestone_creation_batches(selected);
                const endpoint="marina_custom_apps.design_management.clean_milestones.clear_related";
                const esc=frappe.utils.escape_html;
                let preview=null,previewReady=false,working=false;
                let failedIndices=[],successful=new Map(),failureReasons=new Map(),submittedReason=null;
                const revisionsByCode=new Map();
                const dlg=new frappe.ui.Dialog({
                    title:__("Clear Related Milestones in Bulk"),
                    size:"large",
                    fields:[
                        {fieldname:"progress",fieldtype:"HTML",
                         options:'<p class="text-muted">'+esc(__("Preparing milestone reset preview…"))+'</p>'},
                        {fieldname:"preview",fieldtype:"HTML",
                         options:'<p class="text-muted">'+esc(__("Checking the selected designs in batches of 20."))+'</p>'},
                        {fieldname:"reason",fieldtype:"Small Text",reqd:1,
                         label:__("Reason for Clearing"),
                         description:__("10–500 characters; recorded separately in each Design Cleanup Log.")},
                        {fieldname:"confirmed",fieldtype:"Check",reqd:1,
                         label:__("I confirm permanently clearing the selected milestone records")}
                    ],
                    primary_action_label:__("Clear Related Milestones"),
                    primary_action(values){
                        const reason=(values.reason||"").trim();
                        if(working || !previewReady || !preview?.with_milestones)return;
                        if(!values.confirmed || reason.length<10 || reason.length>500){
                            frappe.msgprint(__("Confirm and enter a reason of 10–500 characters."));
                            return;
                        }
                        if(submittedReason!==null && reason!==submittedReason){
                            frappe.msgprint(__("The original clearing reason must remain unchanged when retrying failed batches."));
                            return;
                        }
                        if(submittedReason===null)submittedReason=reason;
                        const pending=failedIndices.length ? [...failedIndices] :
                            batches.map((_,index)=>index).filter(index=>!successful.has(index));
                        if(!pending.length)return;
                        void performBatches(pending,reason);
                    }
                });
                dlg.show();
                dlg.get_primary_btn().prop("disabled",true);
                dlg.$wrapper.on("hide.bs.modal.marinaMilestoneReset",event=>{
                    if(working)event.preventDefault();
                });
                const progress=(phase,completed,total)=>{
                    const percent=total?Math.round(completed*100/total):100;
                    dlg.fields_dict.progress.$wrapper.html(
                        '<div class="mb-2" role="status" aria-live="polite">'+
                            esc(phase+" — "+completed+"/"+total)+
                        '</div><div class="progress" style="height:9px">'+
                            '<div class="progress-bar" role="progressbar" aria-valuenow="'+percent+
                            '" aria-valuemin="0" aria-valuemax="100" style="width:'+percent+
                            '%;background:#551C25"></div></div>'
                    );
                };
                const renderPreview=()=>{
                    const lines=preview.designs.map(item=>
                        '<tr><td>'+esc(item.design_code)+'</td>'+
                        '<td>'+esc(String(item.plans))+'</td>'+
                        '<td>'+esc(String(item.executions))+'</td>'+
                        '<td>'+esc(String(item.events))+'</td>'+
                        '<td>'+esc(item.has_milestones?__("Will Clear"):__("No Milestones — Skip"))+
                        '</td></tr>').join("");
                    const summary='<p>'+esc(__("Selected: {0} | With Milestones: {1} | Without Milestones: {2}",[
                        preview.selected,preview.with_milestones,preview.without_milestones
                    ]))+'</p>'+
                        '<p class="text-muted">'+esc(__("Processing will use {0} sequential batch(es), with a maximum of 20 designs per batch.",[batches.length]))+'</p>'+
                        '<div style="max-height:290px;overflow:auto">'+
                        '<table class="table table-bordered table-sm"><thead><tr>'+
                        '<th>'+esc(__("Design Code"))+'</th><th>'+esc(__("Plans"))+'</th>'+
                        '<th>'+esc(__("Executions"))+'</th><th>'+esc(__("Custody Events"))+
                        '</th><th>'+esc(__("Action"))+'</th></tr></thead><tbody>'+
                        lines+'</tbody></table></div>'+
                        '<p class="text-danger">'+esc(__("Milestone workflows and custody history will be permanently removed from active records. Each completed batch is committed separately and will NOT be rolled back if a later batch fails."))+'</p>'+
                        '<p>'+esc(__("An audit snapshot is retained per cleared Design Code. Design Codes, published evidence, team assignments and production data are preserved. Creation Dates become editable after clearing."))+'</p>';
                    dlg.fields_dict.preview.$wrapper.html(summary);
                };
                const summarizeResults=()=>{
                    const results=[...successful.values()];
                    const cleared=results.reduce((n,result)=>n+Number(result.cleared||0),0);
                    const skipped=results.reduce((n,result)=>n+Number(result.skipped||0),0);
                    const failed=failedIndices.reduce((n,i)=>n+batches[i].length,0);
                    const failedRows=failedIndices.map(i=>
                        '<li><strong>'+esc(__("Batch {0} ({1} designs)",[
                            i+1,batches[i].length
                        ]))+'</strong>: '+esc(batches[i].join(", "))+
                        (failureReasons.has(i)?'<div class="text-muted">'+
                            esc(failureReasons.get(i))+'</div>':"")+'</li>'
                    ).join("");
                    const summary='<p><strong>'+esc(__("Cleared: {0} | Skipped (no milestones): {1} | Failed (not confirmed): {2}",[
                        cleared,skipped,failed
                    ]))+'</strong></p>'+
                        '<p class="text-muted">'+esc(__("Audit reason: {0}",[submittedReason||""]))+'</p>'+
                        (failedRows?'<p class="text-danger">'+esc(__("Failed batches may be retried using the ORIGINAL preview revisions. If milestone data changed, close and run a fresh preview. Never assume a timed-out batch was not committed."))+'</p><ul>'+
                            failedRows+'</ul>':"")+
                        '<p>'+esc(__("Design Code, published evidence and production records are preserved. Plans can be recreated for cleared designs."))+'</p>';
                    return {cleared,skipped,failed,summary};
                };
                async function performBatches(indices,reason){
                    working=true;
                    dlg.get_primary_btn().prop("disabled",true);
                    dlg.$wrapper.find(".modal-header .close").prop("disabled",true);
                    failedIndices=[];
                    for(let pos=0;pos<indices.length;pos++){
                        const index=indices[pos];
                        progress(__("Archiving and clearing milestone batches"),pos,indices.length);
                        const expected_revisions=Object.fromEntries(batches[index].map(name=>[
                            name,revisionsByCode.get(name)
                        ]));
                        try{
                            const {message:result}=await frappe.call({
                                method:endpoint+".bulk_clear_related_milestones",
                                type:"POST",
                                args:{design_codes:batches[index],reason,
                                      expected_revisions,confirm:1}
                            });
                            if(!result || Number(result.selected)!==batches[index].length ||
                               !Array.isArray(result.cleared_designs) ||
                               !Array.isArray(result.skipped_designs) ||
                               Number(result.cleared)+Number(result.skipped)!==batches[index].length){
                                throw new Error(__("Incomplete server confirmation; inspect audit logs before retrying."));
                            }
                            successful.set(index,result);
                            failureReasons.delete(index);
                        }catch(error){
                            console.warn("Milestone reset batch "+(index+1)+" failed",error);
                            failedIndices.push(index);
                            failureReasons.set(index,String(error?.message ||
                                __("Request failed; review Error Log and cleanup audit.")).slice(0,240));
                        }
                        progress(__("Archiving and clearing milestone batches"),pos+1,indices.length);
                    }
                    working=false;
                    dlg.$wrapper.find(".modal-header .close").prop("disabled",false);
                    const outcome=summarizeResults();
                    if(failedIndices.length){
                        dlg.fields_dict.preview.$wrapper.html(outcome.summary);
                        dlg.get_primary_btn().text(__("Retry Failed Batches"));
                        dlg.get_primary_btn().prop("disabled",false);
                        frappe.show_alert({
                            message:__("Some milestone reset batches failed. Review audit and status before retrying."),
                            indicator:"orange"
                        },8);
                        return;
                    }
                    dlg.hide();
                    listview.clear_checked_items();
                    listview.refresh();
                    frappe.msgprint({
                        title:__("Milestone Reset Completed"),
                        indicator:outcome.cleared?"green":"orange",
                        message:outcome.summary
                    });
                }
                // No clearing occurs until EVERY selected design has passed
                // the preview's existing permission, snapshot and link checks.
                try{
                    const parts=[];
                    for(let i=0;i<batches.length;i++){
                        progress(__("Checking milestone records"),i,batches.length);
                        const {message:part}=await frappe.call({
                            method:endpoint+".preview_bulk_clear_related_milestones",
                            type:"POST",args:{design_codes:batches[i]}
                        });
                        if(!part || Number(part.selected)!==batches[i].length ||
                           !Array.isArray(part.designs) || part.designs.length!==batches[i].length){
                            throw new Error(__("Incomplete milestone reset preview for batch {0}",[i+1]));
                        }
                        parts.push(part);
                        progress(__("Checking milestone records"),i+1,batches.length);
                    }
                    const designs=parts.flatMap(part=>part.designs);
                    for(const row of designs){
                        if(typeof row.revision!=="string" || !/^[0-9a-f]{64}$/.test(row.revision)){
                            throw new Error(__("Missing or invalid milestone preview revision. Refresh and retry."));
                        }
                        revisionsByCode.set(row.design_code,row.revision);
                    }
                    if(revisionsByCode.size!==selected.length){
                        throw new Error(__("The selected Design Codes changed during preview. Refresh and retry."));
                    }
                    preview={
                        designs,selected:designs.length,
                        with_milestones:designs.filter(row=>row.has_milestones).length,
                        without_milestones:designs.filter(row=>!row.has_milestones).length
                    };
                    renderPreview();
                    previewReady=true;
                    dlg.get_primary_btn().prop("disabled",!preview.with_milestones);
                }catch(error){
                    console.warn("Marina Design: unable to preview bulk reset",error);
                    dlg.fields_dict.preview.$wrapper.html(
                        '<p class="text-danger">'+esc(__("Milestone reset preview failed. No milestone records were deleted. Close this dialog and retry."))+'</p>'
                    );
                    progress(__("Preview interrupted"),0,batches.length);
                }
            });
        }).catch(error=>{
            console.warn("Marina Design: milestone reset List permission check failed",error);
        });
    },
    formatters:Object.assign({},marina_design_code_previous_formatters,{
        assigned_merchandiser(value,df,doc){
            return marina_design_code_merchandiser_cell(value,doc);
        }
    })
});
