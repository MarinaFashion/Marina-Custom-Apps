/* A new assignment inherits the document's milestone by default.
   Existing mappings are not changed: published evidence stays auditable. */
frappe.ui.form.on("Design Document Assignment", {
    assignments_add(frm, cdt, cdn) {
        const row=locals[cdt]?.[cdn];
        if (row && !row.target_milestone_type && frm.doc.related_milestone_type) {
            frappe.model.set_value(cdt,cdn,"target_milestone_type",
                frm.doc.related_milestone_type);
        }
    }
});

frappe.ui.form.on("Design Document", {
    setup(frm) {
        frm.set_query("filter_subcategory",()=>({
            filters:{parent_category:frm.doc.filter_category||""}
        }));
        frm.set_query("filter_merchandiser",()=>({
            query:"marina_custom_apps.design_management.api.design_documents.search_eligible_users",
            filters:{team:"merchandisers"}
        }));
    },
    filter_category(frm){frm.set_value("filter_subcategory",null);},
    related_milestone_type(frm) {
        // When the parent is set after adding blank, unsaved rows, complete
        // only those new rows. Never rewrite existing or explicit overrides.
        const defaultMilestone=frm.doc.related_milestone_type;
        if (!defaultMilestone) return;
        (frm.doc.assignments||[]).forEach(row=>{
            if (row.__islocal && !row.target_milestone_type) {
                frappe.model.set_value(row.doctype,row.name,
                    "target_milestone_type",defaultMilestone);
            }
        });
    },
    refresh(frm) {
        // Only Published documents require a file; Drafts can be prepared
        // and linked to designs before the Tech Pack is available.
        frm.set_df_property("attachment","reqd",
            (frm.doc.publication_status==="Published" && !(frm.doc.additional_files||[]).length) ? 1 : 0);
        frm.add_custom_button(__("Find Design Codes"),()=> {
            const filters = {};
            [
                ["filter_mood_board","mood_board"],["filter_category","category"],
                ["filter_subcategory","subcategory"],["filter_year","year"],
                ["filter_season","season"],["filter_collection","collection"],
                ["filter_merchandiser","assigned_merchandiser"]
            ].forEach(([input,key])=>{if(frm.doc[input]) filters[key]=frm.doc[input];});
            frappe.call({
                method:"marina_custom_apps.design_management.api.design_documents.preview_design_codes",
                args:{filters,limit:200},
                callback({message}) {
                    const matches=message||[];
                    if (!matches.length) {
                        frappe.msgprint(__("No accessible Design Codes match these filters."));
                        return;
                    }
                    const dialog=new frappe.ui.Dialog({
                        title:__("Select Design Codes"),
                        fields:[{fieldname:"matches",fieldtype:"HTML"}],
                        primary_action_label:__("Add Selected Designs"),
                        primary_action() {
                            const chosen=dialog.fields_dict.matches.$wrapper.find("input[data-design-code]:checked")
                                .map((_,el)=>el.dataset.designCode).get();
                            const added=new Set((frm.doc.assignments||[]).map(x=>x.design_code));
                            chosen.forEach(name=>{
                                if (!added.has(name)) {
                                    const row=frm.add_child("assignments");
                                    row.design_code=name;
                                    row.target_milestone_type=frm.doc.related_milestone_type||"";
                                    added.add(name);
                                }
                            });
                            frm.refresh_field("assignments");
                            frm.set_value("assignment_count",added.size);
                            dialog.hide();
                        }
                    });
                    const esc=frappe.utils.escape_html;
                    const markup=matches.map(d=>
                        '<label class="d-block p-2 border-bottom">'
                        +'<input type="checkbox" data-design-code="'+esc(d.name)+'"> '
                        +esc(d.name)+' — '+esc(d.mood_board || "")+
                        ' — '+esc(d.category || "")
                        +' — '+esc(__("Merchandiser"))+': '
                        +esc(d.assigned_merchandiser_username||__("Unassigned"))+'</label>'
                    ).join("");
                    dialog.show();
                    const wrapper=dialog.fields_dict.matches.$wrapper;
                    wrapper.html(
                        '<p class="text-muted">'+__("Preview only: select designs to assign. New designs will not inherit the file.")+'</p>'
                        +'<div class="d-flex align-items-center justify-content-between p-2 border-bottom">'
                        +'<label class="mb-0"><input type="checkbox" class="marina-design-select-all"> '
                        +__("Select All")+'</label>'
                        +'<span class="text-muted small marina-design-selection-count"></span></div>'
                        +'<div style="max-height:400px;overflow-y:auto">'+markup+'</div>'
                    );
                    // Keep Select All synchronized with individual selections.
                    // Use only this dialog's checkboxes; other page controls
                    // must never be changed by a bulk selection.
                    const selectAll=wrapper.find(".marina-design-select-all");
                    const choices=wrapper.find("input[data-design-code]");
                    const count=wrapper.find(".marina-design-selection-count");
                    const syncSelectAll=()=>{
                        const selected=choices.filter(":checked").length;
                        const total=choices.length;
                        selectAll.prop("checked",total>0 && selected===total);
                        selectAll.prop("indeterminate",selected>0 && selected<total);
                        count.text(__("{0} of {1} selected",[selected,total]));
                    };
                    selectAll.on("change",()=>{
                        choices.prop("checked",selectAll.prop("checked"));
                        syncSelectAll();
                    });
                    choices.on("change",syncSelectAll);
                    syncSelectAll();
                }
            });
        });
    }
});


/* Publication is independent of the workflow. Completing a step checks
   its required evidence; publishing never changes a milestone state. */
frappe.ui.form.on("Design Document",{
    refresh(frm){
        if(frm.is_new() || frm.doc.publication_status==="Published")return;
        frm.add_custom_button(__("Publish Document"),()=>{
            if(!frm.doc.attachment && !(frm.doc.additional_files||[]).some(row=>row.file)){
                frappe.msgprint(__("Attach a primary or additional designer file before publishing this Design Document."));
                frm.scroll_to_field("additional_files");
                return;
            }
            if(frm.is_dirty()){
                frappe.msgprint(__("Save the document and assignments before publishing."));
                return;
            }
            frappe.confirm(__("Publish this document? This does not change milestone statuses."),()=>
                frappe.call({
                    method:"marina_custom_apps.design_management.clean_milestones.publication.publish_document",
                    type:"POST",args:{document_name:frm.doc.name},freeze:true
                }).then(()=>frm.reload_doc()));
        },__("Document"));
    }
});

/* Permission-managed removal of a single published Design Code assignment.
   The document file, publication history and other assignments are untouched. */
frappe.ui.form.on("Design Document", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.publication_status !== "Published"
            || !(frm.doc.assignments || []).length) return;
        const name = frm.doc.name;
        frappe.call({
            method:"marina_custom_apps.design_management.api.design_documents.can_remove_published_assignment",
            args:{document_name:name}
        }).then(({message:allowed})=>{
            if (!allowed || frm.doc.name !== name) return;
            frm.add_custom_button(__("Remove Published Assignment"),()=>{
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save your document changes before removing an assignment."));
                    return;
                }
                const assignments=(frm.doc.assignments||[]).map(row=>row.design_code).filter(Boolean);
                const dialog=new frappe.ui.Dialog({
                    title:__("Remove Published Assignment"),
                    fields:[
                        {fieldname:"design_code",label:__("Design Code"),
                         fieldtype:"Select",options:assignments.join("\\n"),reqd:1},
                        {fieldname:"reason",label:__("Reason"),fieldtype:"Small Text",reqd:1}
                    ],
                    primary_action_label:__("Remove Assignment"),
                    primary_action(values){
                        frappe.confirm(
                            __("Remove {0} from this published document? The file stays unchanged.",
                               [values.design_code]), ()=>
                            frappe.call({
                                method:"marina_custom_apps.design_management.api.design_documents.remove_published_assignment",
                                type:"POST",
                                args:{document_name:name,design_code:values.design_code,reason:values.reason},
                                freeze:true
                            }).then(()=>{
                                dialog.hide();
                                frm.reload_doc();
                            })
                        );
                    }
                });
                dialog.show();
            },__("Document"));
        });
    }
});


/* Publish-aware assignment corrections:
   - Appending new Design Codes remains available through Find Design Codes
     and Save even while Published.
   - Unpublish for Revision only when the document is not already used as
     milestone evidence. Published attachments never change in place.
*/
frappe.ui.form.on("Design Document", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.publication_status !== "Published") return;
        frm.set_intro(__("To include additional styles, use Find Design Codes, add the missing designs, and Save. Existing published assignments and the attached file remain unchanged."), "blue");
        const name = frm.doc.name;
        frappe.call({
            method:"marina_custom_apps.design_management.clean_milestones.publication.can_unpublish_document",
            args:{document_name:name}
        }).then(({message:allowed})=>{
            if (!allowed || frm.is_new() || frm.doc.name !== name ||
                frm.doc.publication_status !== "Published") return;
            frm.add_custom_button(__("Unpublish for Revision"),()=>{
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save or discard document changes before unpublishing."));
                    return;
                }
                frappe.confirm(__("Move this document back to Draft for revision? " +
                    "It must be republished before it can be used as milestone evidence."),()=>{
                    frappe.call({
                        method:"marina_custom_apps.design_management.clean_milestones.publication.unpublish_document",
                        type:"POST",args:{document_name:name},freeze:true
                    }).then(()=>frm.reload_doc());
                });
            },__("Document"));
        });
    }
});


/* Standalone publication: a Tech Pack may be Published before it is linked
   to any Design Code; the milestone evidence dialog confirms the link later. */
frappe.ui.form.on("Design Document", {
    refresh(frm) {
        if (frm.doc.publication_status === "Published") return;
        if (!(frm.doc.assignments||[]).length) {
            frm.set_intro(__(
                "You can publish this document after attaching its file, without assigning a Design Code. The responsible user can link it when confirming milestone evidence."
            ), "blue");
        }
    }
});

/* Controlled cleanup of unlinked Draft working documents.
   Requires explicit Design Document Delete permission; server rechecks
   ownership, references and status before executing the deletion. */
frappe.ui.form.on("Design Document", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.publication_status !== "Draft") return;
        if ((frm.doc.assignments || []).some(row => row.design_code)) return;
        const document_name = frm.doc.name;
        frappe.call({
            method: "marina_custom_apps.design_management.api.design_documents.can_delete_unlinked_draft",
            args: {document_name}
        }).then(({message: allowed}) => {
            if (!allowed || frm.doc.name !== document_name ||
                    frm.doc.publication_status !== "Draft") return;
            frm.add_custom_button(__("Delete Unlinked Draft"), () => {
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save or discard unsaved changes before deleting this document."));
                    return;
                }
                frappe.confirm(
                    __("Permanently delete this unlinked Draft Design Document? Frappe may also remove attachments associated with this document."),
                    () => frappe.call({
                        method: "marina_custom_apps.design_management.api.design_documents.delete_unlinked_draft",
                        type: "POST",
                        args: {document_name},
                        freeze: true
                    }).then(() => {
                        frappe.show_alert({message: __("Draft Design Document deleted"), indicator: "green"});
                        frappe.set_route("List", "Design Document");
                    })
                );
            }, __("Document"));
        });
    }
});

/* Controlled published-file replacement: create a NEW Published version.
   Never overwrite a file referenced by historic milestone evidence. */
frappe.ui.form.on("Design Document", {
    refresh(frm) {
        if (frm.is_new() || frm.doc.publication_status !== "Published" ||
                frm.doc.superseded_by) return;
        const source = frm.doc.name;
        const method = "marina_custom_apps.design_management.clean_milestones.published_revisions";
        frappe.call({
            method: method + ".can_replace_published_file",
            args: {document_name: source}
        }).then(({message: allowed}) => {
            if (!allowed || frm.doc.name !== source ||
                    frm.doc.publication_status !== "Published" ||
                    frm.doc.superseded_by) return;
            frm.add_custom_button(__("Replace Published File"), () => {
                if (frm.is_dirty()) {
                    frappe.msgprint(__("Save or discard unsaved changes before replacing the published file."));
                    return;
                }
                const sourceFiles = [
                    ...(frm.doc.attachment ? [{url: frm.doc.attachment, label: __("Primary File")}] : []),
                    ...(frm.doc.additional_files || []).filter(row => row.file)
                        .map(row => ({
                            url: row.file,
                            label: row.designer || row.description || __("Additional File")
                        }))
                ];
                const dialog = new frappe.ui.Dialog({
                    title: __("Publish Replacement File"),
                    fields: [
                        {fieldname: "replace_target", label: __("Existing File to Replace"),
                         fieldtype: "Select", reqd: 1,
                         options: sourceFiles.map(item => item.url).join("\\n"),
                         description: __("Choose the existing file. Other designer files remain unchanged in the new version.")},
                        {fieldname: "file_url", label: __("Replacement File"),
                         fieldtype: "Attach", reqd: 1,
                         description: __("A new published Design Document will be created. The earlier version and historical milestone evidence remain unchanged.")},
                        {fieldname: "reason", label: __("Revision Reason"),
                         fieldtype: "Small Text", reqd: 1,
                         description: __("Describe what changed in this Tech Pack or Mood Board (10–500 characters).")}
                    ],
                    primary_action_label: __("Publish New Version"),
                    primary_action(values) {
                        const reason = (values.reason || "").trim();
                        if (reason.length < 10 || reason.length > 500) {
                            frappe.msgprint(__("Enter a revision reason of 10–500 characters."));
                            return;
                        }
                        frappe.confirm(__("Publish a replacement for {0}? The earlier version and any historic approvals will remain unchanged.", [source]), () => {
                            frappe.call({
                                method: method + ".replace_published_file",
                                type: "POST", freeze: true,
                                args: {document_name: source,
                                       file_url: values.file_url,
                                       replace_target: values.replace_target, reason}
                            }).then(({message}) => {
                                dialog.hide();
                                frappe.set_route("Form", "Design Document", message.replacement);
                            });
                        });
                    }
                });
                dialog.show();
                if (sourceFiles.length) dialog.set_value("replace_target", sourceFiles[0].url);
            }, __("Document"));
        });
    }
});
