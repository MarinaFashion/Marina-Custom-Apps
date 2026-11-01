/* Marina Design Cost Breakdown: UI only. Controller and API are the authority. */
function marina_cost_api(method,args,after){
    return frappe.call({
        method:"marina_custom_apps.design_management.cost_breakdown_api."+method,
        type:"POST",args,freeze:true,freeze_message:__("Processing commercial costing")
    }).then(({message})=>after?.(message)).catch(error=>{
        console.warn("Cost Breakdown action failed",error);
    });
}
function marina_cost_defaults(frm){
    if(!frm.doc.design_code || !frm.is_new())return;
    const name=frm.doc.design_code;
    frappe.call({
        method:"marina_custom_apps.design_management.cost_breakdown_api.design_cost_defaults",
        args:{design_code:name}
    }).then(({message:info})=>{
        if(!info || frm.doc.design_code!==name || !frm.is_new())return;
        const values={};
        if(!frm.doc.factory && info.factory)values.factory=info.factory;
        if(!frm.doc.currency && info.currency)values.currency=info.currency;
        if(Object.keys(values).length)frm.set_value(values);
        frm.__marina_cost_variants=info.variants||[];
        if(!frm.doc.quotation_date)frm.set_value("quotation_date",frappe.datetime.get_today());
    });
}
function marina_import_production_variants(frm){
    if(!frm.doc.design_code)return;
    frappe.call({
        method:"marina_custom_apps.design_management.cost_breakdown_api.design_cost_defaults",
        args:{design_code:frm.doc.design_code}
    }).then(({message:info})=>{
        if(!info)return;
        const present=new Set((frm.doc.price_qty_lines||[]).map(r=>r.production_key).filter(Boolean));
        let added=0;
        (info.variants||[]).forEach(variant=>{
            if(!variant.production_key || present.has(variant.production_key))return;
            // Do not overwrite quantities or commercial prices already typed
            // by the Merchandiser. Imported prices are suggestions only.
            const line=frm.add_child("price_qty_lines");
            line.production_key=variant.production_key;
            line.variant_code=variant.variant_code;
            line.planned_item_code=variant.planned_item_code;
            line.proposed_qty=variant.proposed_qty||0;
            line.negotiated_unit_price=variant.negotiated_unit_price||0;
            present.add(variant.production_key);
            added++;
        });
        frm.refresh_field("price_qty_lines");
        frappe.show_alert({
            message:__("Imported {0} new planned color(s); review quoted prices and quantities.",[added]),
            indicator:"blue"
        },5);
    });
}
frappe.ui.form.on("Design Cost Breakdown",{
    onload(frm){
        if(frm.is_new() && frm.doc.design_code)marina_cost_defaults(frm);
    },
    design_code(frm){
        if(frm.is_new()){
            frm.clear_table("cost_components");
            frm.clear_table("price_qty_lines");
            frm.refresh_field("cost_components");
            frm.refresh_field("price_qty_lines");
            marina_cost_defaults(frm);
        }
    },
    refresh(frm){
        const locked=!frm.is_new() && ["Pending Approval","Approved","Superseded","Cancelled"].includes(frm.doc.status);
        const fields=["design_code","factory","costing_method","quotation_date",
            "quotation_reference","quotation_attachment","currency","incoterm",
            "exchange_rate_sar","cost_components","price_qty_lines","commercial_remarks"];
        fields.forEach(field=>frm.set_df_property(field,"read_only",locked?1:0));
        if(locked)frm.disable_save();
        else if(typeof frm.has_perm==="function" &&
                frm.has_perm(frm.is_new()?"create":"write"))frm.enable_save();
        const canEdit=!locked && typeof frm.has_perm==="function" &&
            frm.has_perm(frm.is_new()?"create":"write");
        if(frm.doc.design_code && canEdit){
            frm.add_custom_button(__("Import Planned Colors"),()=>marina_import_production_variants(frm),__("Costing"));
        }
        if(frm.is_new() || !frm.doc.name)return;
        const currentName=frm.doc.name;
        frappe.call({
            method:"marina_custom_apps.design_management.cost_breakdown_api.cost_actions",
            args:{name:frm.doc.name}
        }).then(({message:actions})=>{
            if(!actions || frm.doc.name!==currentName)return;
            if(actions.can_submit){
                frm.add_custom_button(__("Submit for Approval"),()=>{
                    if(frm.is_dirty()){
                        frappe.msgprint(__("Save the Cost Breakdown before submitting."));
                        return;
                    }
                    frappe.confirm(__("Submit this commercial quotation and lock it for Buying Manager review?"),
                        ()=>marina_cost_api("submit_cost_breakdown",{name:frm.doc.name},()=>frm.reload_doc()));
                },__("Approval"));
            }
            if(actions.can_return){
                frm.add_custom_button(__("Return for Revision"),()=>{
                    const d=new frappe.ui.Dialog({
                        title:__("Return Cost Breakdown"),
                        fields:[{fieldname:"reason",fieldtype:"Small Text",label:__("Return Reason"),reqd:1,
                            description:__("Explain the required corrections (10–500 characters).")}],
                        primary_action_label:__("Return"),
                        primary_action(values){
                            const reason=(values.reason||"").trim();
                            if(reason.length<10||reason.length>500){
                                frappe.msgprint(__("Enter a reason of 10–500 characters."));
                                return;
                            }
                            d.get_primary_btn().prop("disabled",true);
                            marina_cost_api("return_cost_breakdown",{name:frm.doc.name,reason},
                                ()=>{d.hide();frm.reload_doc();})
                                .finally(()=>d.get_primary_btn().prop("disabled",false));
                        }
                    });
                    d.show();
                },__("Approval"));
            }
            if(actions.can_approve){
                frm.add_custom_button(__("Approve Cost Breakdown"),()=>{
                    frappe.confirm(__("Approve these negotiated prices and quantities as the commercial baseline?"),
                        ()=>marina_cost_api("approve_cost_breakdown",{name:frm.doc.name},()=>frm.reload_doc()));
                },__("Approval"));
            }
            if(actions.can_cancel){
                frm.add_custom_button(__("Cancel Approval"),()=>{
                    if(frm.is_dirty()){
                        frappe.msgprint(__("Save or discard unsaved changes before cancelling approval."));
                        return;
                    }
                    const d=new frappe.ui.Dialog({
                        title:__("Cancel Approved Cost Breakdown"),
                        fields:[
                            {fieldname:"warning",fieldtype:"HTML",
                             options:'<p class="text-danger">'+frappe.utils.escape_html(
                                 __("This will revoke the current approval. Original prices, quantities and approval history remain locked. No previous revision will be approved automatically.")
                             )+'</p>'},
                            {fieldname:"reason",fieldtype:"Small Text",
                             label:__("Cancellation Reason"),reqd:1,
                             description:__("Required for the audit record (10–500 characters).")},
                            {fieldname:"confirm_cancel",fieldtype:"Check",reqd:1,
                             label:__("I confirm revoking this approval")}
                        ],
                        primary_action_label:__("Cancel Approval"),
                        primary_action(values){
                            const reason=(values.reason||"").trim();
                            if(!values.confirm_cancel || reason.length<10 || reason.length>500){
                                frappe.msgprint(__("Confirm cancellation and enter a reason of 10–500 characters."));
                                return;
                            }
                            d.get_primary_btn().prop("disabled",true);
                            marina_cost_api("cancel_approved_cost_breakdown",{
                                name:currentName,reason
                            },()=>{
                                d.hide();
                                frm.reload_doc();
                                frappe.show_alert({
                                    message:__("Approval cancelled. Create a new revision to resubmit pricing."),
                                    indicator:"orange"
                                },7);
                            }).finally(()=>d.get_primary_btn().prop("disabled",false));
                        }
                    });
                    d.show();
                },__("Approval"));
            }
            if(actions.can_revise){
                frm.add_custom_button(__("Create New Revision"),()=>{
                    frappe.confirm(__("Create an editable new version while preserving this approved quotation?"),
                        ()=>marina_cost_api("create_cost_revision",{source_name:frm.doc.name},result=>{
                            if(result?.name)frappe.set_route("Form","Design Cost Breakdown",result.name);
                        }));
                },__("Approval"));
            }
        });
    }
});
