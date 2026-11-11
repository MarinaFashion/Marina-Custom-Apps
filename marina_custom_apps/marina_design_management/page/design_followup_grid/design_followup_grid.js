/* Clean milestone follow-up — all transitions/permissions are server enforced. */
/* Design-specific baseline preview; server independently validates inputs.
   Uses proportional cumulative rounding just like planning_overrides.py. */
function marinaProjectDesignPlan(types, selected, customDays, designDate) {
    const byName=new Map(types.map(t=>[t.name,t]));
    const cache=new Map(), visiting=new Set();
    const shift=(iso,days)=>{
        if(!/^\d{4}-\d{2}-\d{2}$/.test(iso||""))return null;
        const d=new Date(iso+"T00:00:00Z");
        if(isNaN(d.getTime()))return null;
        d.setUTCDate(d.getUTCDate()+days);
        return d.toISOString().slice(0,10);
    };
    const portions=t=>{
        const raw=(t.workflow_steps||[]).map(x=>Number(x.lead_time_days||0));
        if(!raw.length)return [];
        const chosen=customDays[t.name];
        if(!Number.isInteger(chosen)||chosen<0||chosen>3650)return null;
        if(raw.length===1)return chosen===0?[0]:null;
        const base=raw.slice(1).reduce((a,b)=>a+b,0);
        let cumulative=0,previous=0;
        const values=raw.slice(1).map((weight,i,all)=>{
            if(!base)return i===all.length-1?chosen:0;
            cumulative+=weight;
            const rounded=Math.floor((cumulative*chosen+Math.floor(base/2))/base);
            const result=rounded-previous;previous=rounded;
            return result;
        });
        return [0,...values];
    };
    const calculate=name=>{
        if(cache.has(name))return cache.get(name);
        if(visiting.has(name)||!selected.has(name)||!byName.has(name))return null;
        visiting.add(name);
        const t=byName.get(name),parts=portions(t);
        let start=null;
        if(parts){
            if(Number(t.start_with_design_creation))start=designDate;
            else{
                const parent=calculate(t.depends_on_type);
                const parentType=byName.get(t.depends_on_type);
                const parentParts=parentType && portions(parentType);
                const trigger=t.r22_trigger_status||"Completed";
                const at=(parentType?.workflow_steps||[]).findIndex(x=>x.step===trigger);
                if(parent && parentParts && at>=0 && trigger!=="Rework"){
                    start=shift(parent.start,
                        parentParts.slice(1,at+1).reduce((a,b)=>a+b,0));
                }
            }
        }
        const result=start && parts ? {
            start,due:shift(start,parts.slice(1).reduce((a,b)=>a+b,0))
        }:null;
        visiting.delete(name);
        cache.set(name,result);
        return result;
    };
    const result={};
    types.forEach(t=>{result[t.name]=calculate(t.name);});
    return result;
}


/* Grouped, Excel-style design follow-up. Same clean workflow service,
   no direct status mutations, no N+1 browser API calls. */
frappe.pages["design-followup-grid"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper, title: __("Production Follow-Up Grid"), single_column: true
    });
    $(wrapper).addClass("mdm-followup-page");
    const root = $('<div class="p-3 mdm-followup-grid"></div>').appendTo(page.main);
    // Page-scoped Warm Signature styling; no global Desk theme changes,
    // web-font downloads, resize listeners or additional API calls.
    $('<style>').text(`
        .mdm-followup-page .page-head-content {
            background:#551c25; border-radius:8px; padding:12px 18px;
        }
        .mdm-followup-page .page-head-content .title-text { color:#fff; }
        .mdm-followup-page .mdm-followup-grid {
            background:#f2ebe7; color:#2d2926; border-radius:8px;
            font-family:Inter,"Segoe UI",Arial,sans-serif; font-size:15px;
        }
        .mdm-followup-grid .mdm-followup-filters {
            display:grid !important; grid-template-columns:repeat(4,minmax(0,1fr));
            align-items:start !important; padding:20px; background:#fff;
            border-radius:7px; gap:18px 20px !important;
        }
        .mdm-followup-grid .mdm-followup-filter { min-width:0; }
        .mdm-followup-grid .mdm-filter-label {
            color:#2d2926; font-size:14px; font-weight:600; line-height:20px;
            white-space:nowrap; margin-bottom:8px !important;
        }
        .mdm-followup-grid .mdm-followup-filter .frappe-control,
        .mdm-followup-grid .mdm-followup-filter .form-group { margin-bottom:0; }
        .mdm-followup-grid .mdm-followup-filter .form-control {
            height:40px; min-height:40px; font-size:15px; line-height:22px;
            padding-top:8px; padding-bottom:8px; background:#fff;
            color:#2d2926; border:1px solid #c0a392; border-radius:5px;
        }
        .mdm-followup-grid .form-control:focus {
            border-color:#551c25; box-shadow:0 0 0 2px rgba(85,28,37,.15);
        }
        .mdm-followup-grid .mdm-custody-shortcut {
            display:inline-block; margin-top:6px; font-size:13px; color:#551c25;
        }
        .mdm-followup-grid .btn { font-size:14px; }
        .mdm-followup-grid .btn-default {
            background:#fff; color:#551c25; border:1px solid #c0a392;
        }
        .mdm-followup-grid .btn-primary {
            background:#551c25; color:#fff; border-color:#551c25;
        }
        .mdm-followup-grid .btn-primary:not(:disabled):hover { background:#6c2934; }
        .mdm-followup-grid .small { font-size:13px; }
        .mdm-followup-grid .text-muted { color:#70625b !important; }
        .mdm-followup-grid .text-info { color:#551c25 !important; }
        .mdm-followup-grid a { color:#551c25; }
        .mdm-followup-grid .table-responsive {
            background:#fff; border:1px solid #c0a392; border-radius:6px;
        }
        .mdm-followup-grid .mdm-grid-table { font-size:15px; margin-bottom:0; }
        .mdm-followup-grid .mdm-grid-table th {
            background:#e4d5c4; color:#551c25; font-size:14px;
            font-weight:600; white-space:nowrap; padding:12px 10px;
        }
        .mdm-followup-grid .mdm-grid-table td {
            padding:10px; vertical-align:middle; border-color:#e4d5c4;
        }
        .mdm-followup-grid .mdm-grid-table .table-active > td { background:#f2ebe7; }
        .mdm-followup-grid .mdm-grid-note { font-size:14px; background:#fff; color:#2d2926; }
        .mdm-followup-grid .mdm-grid-toolbar { align-items:flex-start !important; }
        .mdm-followup-grid .mdm-grid-toolbar > .mdm-grid-info { flex:1 1 280px; }
        .mdm-followup-grid .mdm-grid-toolbar > .mdm-grid-actions { flex-wrap:wrap; }
        @media(max-width:1199px) {
            .mdm-followup-grid .mdm-followup-filters { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        @media(max-width:575px) {
            .mdm-followup-grid .mdm-followup-filters { grid-template-columns:minmax(0,1fr); padding:14px; }
        }
    `).appendTo(root);
    // Four equal columns on desktop (two rows), then two/one on smaller
    // screens. Labels stay above their fields; Link wrappers cannot shift them.
    const filters = $('<div class="mdm-followup-filters d-flex flex-wrap align-items-end mb-2"></div>')
        .css({gap:"12px",width:"100%"}).appendTo(root);
    const filterColumn = (label,basis) => {
        const col=$('<div class="mdm-followup-filter"></div>')
            .css({flexBasis:basis,minWidth:0}).appendTo(filters);
        const heading=$('<label class="mdm-filter-label mb-1 d-block"></label>')
            .css("min-height","20px").text(label).appendTo(col);
        return {col,heading};
    };
    const searchBox=filterColumn(__("Search"),"210px");
    const search=$('<input type="text" class="form-control input-sm">')
        .attr({id:"mdm-grid-search",placeholder:__("Design Code / Mood Board")})
        .css("width","100%").appendTo(searchBox.col);
    searchBox.heading.attr("for","mdm-grid-search");
    const multiRow=$('<div class="d-flex align-items-center flex-wrap mt-1"></div>')
        .css({gap:"6px"}).appendTo(searchBox.col);
    const multiButton=$('<button type="button" class="btn btn-default btn-xs"></button>')
        .text(__("Multiple Codes")).appendTo(multiRow);
    const multiCount=$('<span class="text-muted small"></span>').appendTo(multiRow);
    const multiClear=$('<button type="button" class="btn btn-link btn-xs p-0"></button>')
        .text(__("Clear")).hide().appendTo(multiRow);
    const makeLink = (fieldname, box, doctype) => {
        const control=frappe.ui.form.make_control({
            parent:box.col,
            df:{fieldtype:"Link",fieldname,label:"",options:doctype,
                hide_label:1},
            render_input:true
        });
        control.refresh();
        const inputId="mdm-grid-"+fieldname;
        control.$input.attr("id",inputId);
        box.heading.attr("for",inputId);
        // Frappe Link fields otherwise introduce a second label and
        // variable bottom margins compared with native filter controls.
        control.$wrapper?.find(".control-label").hide();
        control.$wrapper?.find(".form-group, .frappe-control").css("margin-bottom","0");
        return control;
    };
    const hierarchyChoices={
        season:["Ramadan","Summer","Winter"],
        collection:["EID","Ramadan","Hajj","Summer","Autumn","Winter"]
    };
    const hierarchyFilters={};
    for(const key of ["season","collection"]){
        const box=filterColumn(__(key[0].toUpperCase()+key.slice(1)),"145px");
        const select=$('<select class="form-control input-sm"></select>').appendTo(box.col);
        $('<option>').val("").text(__("All")).appendTo(select);
        hierarchyChoices[key].forEach(value=>
            $('<option>').val(value).text(value).appendTo(select));
        hierarchyFilters[key]=select;
    }
    const custodyBox=filterColumn(__("Custody"),"170px");
    const custody=makeLink("custody",custodyBox,"User");
    custody.get_query=()=>({
        query:"marina_custom_apps.design_management.security.participants.search_participant_users",
        filters:{}
    });
    custody.df.get_query=custody.get_query;
    const meShortcut=$('<a href="#" class="mdm-custody-shortcut"></a>')
        .text(__("Assigned to Me")).appendTo(custodyBox.col);
    meShortcut.on("click",e=>{
        e.preventDefault();
        Promise.resolve(custody.set_value(frappe.session.user))
            .then(()=>apply.trigger("click"));
    });
    const mood=makeLink("mood_board",filterColumn(__("Mood Board"),"155px"),"Mood Board");
    const designer=makeLink("designer",filterColumn(__("Designer"),"155px"),"User");
    designer.get_query=()=>({
        query:"marina_custom_apps.design_management.security.participants.search_participant_users",
        filters:{owner_field:"designer"}
    });
    designer.df.get_query=designer.get_query;
    const milestoneBox=filterColumn(__("Milestone Type"),"160px");
    const milestoneType=$('<select class="form-control input-sm"></select>')
        .attr("id","mdm-grid-milestone-type").appendTo(milestoneBox.col);
    $('<option>').val("").text(__("All Milestone Types")).appendTo(milestoneType);
    milestoneBox.heading.attr("for","mdm-grid-milestone-type");
    // Load milestone masters once, not on every filter.
    frappe.call({
        method:"marina_custom_apps.design_management.clean_milestones.api.followup_milestone_types"
    }).then(({message:types})=>{
        (types||[]).forEach(name=>
            $('<option>').val(name).text(name).appendTo(milestoneType));
        const chosen=state.dashboard?.milestone||milestoneType.data("pending-value");
        if(chosen)milestoneType.val(chosen);
    }).catch(error=>{
        console.warn("Unable to load Milestone Type options",error);
        $('<option>').val("").prop("disabled",true)
            .text(__("Milestone types unavailable — reload page")).appendTo(milestoneType);
    });
    const viewBox=filterColumn(__("Group By"),"140px");
    const groupBy=$('<select class="form-control input-sm"></select>')
        .append(
            $('<option>').val("design").text(__("Design Code")),
            $('<option>').val("milestone").text(__("Milestone")),
            $('<option>').val("user").text(__("User (Custodian)"))
        ).appendTo(viewBox.col);
    const statusBox=filterColumn(__("Show Milestones"),"160px");
    const milestoneFilter=$('<select class="form-control input-sm"></select>')
        .appendTo(statusBox.col);
    [["all", __("All Milestones")], ["active", __("Current Milestones")],
     ["completed", __("Completed Milestones")],
     ["future", __("Future Milestones")]].forEach(([value,label])=>
        $('<option></option>').val(value).text(label).appendTo(milestoneFilter));
    milestoneFilter.val("active");
    const sizeBox=filterColumn(__("Designs / Page"),"105px");
    const size=$('<select class="form-control input-sm"></select>')
        .append($('<option>').text("20"),
                $('<option>').text("50").prop("selected",true),
                $('<option>').text("100")).appendTo(sizeBox.col);

    const factoryBox=filterColumn(__("Factory"),"155px");
    const factory=$('<select class="form-control input-sm"></select>')
        .attr("id","mdm-grid-factory")
        .append($('<option>').val("").text(__("All Factories")))
        .appendTo(factoryBox.col);
    factoryBox.heading.attr("for","mdm-grid-factory");
    // Reuse the configured Design Code factory list once per page instance.
    Promise.resolve(frappe.call({
        method:"marina_custom_apps.design_management.factory_options.get_factory_options"
    })).then(response=>{
        (response.message||[]).forEach(name=>
            $('<option>').val(name).text(name).appendTo(factory));
    }).catch(error=>{
        console.warn("Unable to load Factory filter choices",error);
        $('<option>').prop("disabled",true)
            .text(__("Factory choices unavailable — reload page")) .appendTo(factory);
    });

    [search,groupBy,milestoneFilter,size].forEach(el=>el.css("width","100%"));
    [[groupBy,viewBox,"group"],[milestoneFilter,statusBox,"milestones"],
     [size,sizeBox,"size"]].forEach(([control,box,key])=>{
        const id="mdm-grid-"+key;
        control.attr("id",id);
        box.heading.attr("for",id);
    });
    const filterActions=$('<div class="d-flex flex-wrap justify-content-end mb-3"></div>')
        .css({gap:"8px"}).appendTo(root);
    const apply=$('<button type="button" class="btn btn-primary btn-sm"></button>')
        .text(__("Apply Filters")).appendTo(filterActions);
    const refresh=$('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Refresh")).appendTo(filterActions);
    const clearDashboard=$('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Clear Dashboard Filter")).hide().prependTo(filterActions);
    const toolbar = $('<div class="mdm-grid-toolbar d-flex flex-wrap align-items-center justify-content-between mb-2"></div>')
        .css("gap","10px").appendTo(root);
    const info = $('<span class="mdm-grid-info text-muted small"></span>').appendTo(toolbar);
    const bar = $('<div class="mdm-grid-actions d-flex align-items-center"></div>').css("gap","8px").appendTo(toolbar);
    const expandAll = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Expand All")).appendTo(bar);
    const collapseAll = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Collapse All")).appendTo(bar);
    const save = $('<button type="button" class="btn btn-primary btn-sm"></button>')
        .text(__("Save Notes")).prop("disabled",true).appendTo(bar);
    const bulkAll=$('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Select All")).hide().appendTo(bar);
    const bulkComplete=$('<button type="button" class="btn btn-primary btn-sm"></button>')
        .text(__("Complete Selected")).prop("disabled",true).hide().appendTo(bar);
    const bulkCount=$('<span class="small text-muted"></span>').hide().appendTo(bar);
    const prev = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Previous")).appendTo(bar);
    const number = $('<span class="small"></span>').appendTo(bar);
    const next = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Next")).appendTo(bar);
    const surface = $('<div class="table-responsive"></div>').appendTo(root);
    const footer = $('<div class="d-flex flex-wrap align-items-center justify-content-end mt-3"></div>')
        .css("gap","8px").appendTo(root).hide();
    const footerPrev = prev.clone().appendTo(footer);
    const footerNumber = number.clone().appendTo(footer);
    const footerNext = next.clone().appendTo(footer);
    // Reuse the same navigation and unsaved-note guard at both ends.
    footerPrev.on("click",()=>prev.trigger("click"));
    footerNext.on("click",()=>next.trigger("click"));
    const esc = v => frappe.utils.escape_html(String(v??""));
    const endpoint = (method,args,post=false) => frappe.call({
        method:"marina_custom_apps.design_management.clean_milestones.api."+method,
        args, type:post?"POST":"GET", freeze:post
    }).then(response=>response.message);
    // A collapsed Design remains collapsed across refresh/page/filter changes.
    // Keep this client-only state separate from unsaved edits and server status.
    let state = {page:1,data:null,dirty:new Map(),request:0,
                 expanded:new Set(),view:"design",milestoneFilter:"active",
                 appliedCustody:"",selectedMilestone:"",designCodes:[],dashboard:null,
                 selectedBulk:new Map()};
    const showMultiCount = () => {
        const count=state.designCodes.length;
        multiCount.text(count?count+" "+__("selected"):"");
        multiClear.toggle(Boolean(count));
        multiButton.toggleClass("btn-primary",Boolean(count))
            .toggleClass("btn-default",!count);
    };
    const parsePastedCodes = value =>
        [...new Set(String(value||"").split(/[\r\n\t,;]+/)
            .map(code=>code.trim()).filter(Boolean))];
    multiButton.on("click",()=>{
        const dialog=new frappe.ui.Dialog({
            title:__("Filter Multiple Design Codes"),
            fields:[{
                fieldtype:"Small Text",fieldname:"codes",
                label:__("Design Codes"),reqd:1,
                default:state.designCodes.join("\n"),
                description:__("Paste from Excel: one code per line, or separate with tabs, commas or semicolons. Maximum 500 unique codes. Exact matches only.")
            }],
            primary_action_label:__("Apply Codes"),
            primary_action(values){
                const codes=parsePastedCodes(values.codes);
                if(!codes.length || codes.length>500 ||
                        codes.some(code=>code.length>140 || /\s/.test(code))){
                    frappe.msgprint(__("Enter 1–500 valid Design Codes (maximum 140 characters each)."));
                    return;
                }
                dirtyGuard(()=>{
                    state.designCodes=codes;
                    showMultiCount();
                    state.page=1;
                    dialog.hide();
                    reload();
                });
            }
        });
        dialog.show();
    });
    multiClear.on("click",()=>dirtyGuard(()=>{
        state.designCodes=[];
        showMultiCount();
        state.page=1;
        reload();
    }));
    // Bulk completion works with any filters; Multiple Codes is optional.
    const bulkEnabled=()=>state.milestoneFilter==="active";
    const bulkEligible=row=>Boolean(row.execution && row.plan_state==="Active" &&
        row.current_custodian && (row.allowed_steps||[]).includes("Completed"));
    const updateBulkActions=()=>{
        const enabled=bulkEnabled();
        bulkAll.toggle(enabled);
        bulkComplete.toggle(enabled).prop("disabled",!state.selectedBulk.size);
        bulkCount.toggle(enabled).text(
            __("{0} selected (this page, max 50)",[state.selectedBulk.size]));
    };
    // Classify by plan state: Rework remains Current, not Completed.
    const showMilestone = row =>
        (!state.dashboard || row.milestone_type===state.dashboard.milestone) &&
        (!state.selectedMilestone || row.milestone_type===state.selectedMilestone) &&
        (state.milestoneFilter==="all" ||
         row.plan_state === ({active:"Active",completed:"Completed",
                             future:"Planned"}[state.milestoneFilter])) &&
        (!state.appliedCustody || row.current_custodian===state.appliedCustody);
    const allRows = () => (state.data?.designs||[]);
    const changeButton = () => {
        const count=state.dirty.size;
        save.prop("disabled",!count).text(count?__("Save Notes")+" ("+count+")":__("Save Notes"));
    };
    const dirtyGuard = callback => {
        if(!state.dirty.size){callback();return;}
        frappe.confirm(__("Discard unsaved milestone notes?"),()=>{
            state.dirty.clear();changeButton();callback();
        });
    };
    const statusClass = (row) => {
        if(row.status!=="Completed" && row.due_date && row.due_date < (state.data?.as_of||""))return "text-danger";
        if(row.status==="Completed")return "text-success";
        if(row.status==="Rework")return "text-warning";
        return "";
    };
    const actionLabel = (status,step) => {
        if(step==="Ready")return __("Submit for Review");
        if(step==="Rework")return __("Return for Rework");
        if(step==="Completed" && status==="Ready")return __("Approve & Complete");
        return __(step);
    };
    const imageHTML = design => design.image ?
        '<img src="'+esc(design.image)+'" loading="lazy" decoding="async" alt="" '+
        'style="height:60px;width:48px;object-fit:cover;border-radius:5px;margin-right:10px;flex:none">' :
        '<span class="d-inline-block bg-light rounded mr-2" '+
        'style="height:60px;width:48px;flex:none"></span>';
    const designTitleHTML = (design,di) =>
        '<a href="#" class="mdm-open-design" data-design="'+di+'">'+
        esc(design.name)+'</a> '+
        '<button type="button" class="btn btn-default btn-xs mdm-design-history" '+
        'data-design="'+di+'">'+esc(__("History"))+'</button> '+
        '<button type="button" class="btn btn-default btn-xs mdm-design-discussion" data-design="'+di+'">'+esc(__("Discussion"))+'</button>';
    const designIdentityHTML = (design,di) =>
        '<div class="d-flex align-items-center">'+imageHTML(design)+
        '<div style="min-width:125px">'+designTitleHTML(design,di)+
        '<div class="small text-muted">'+esc(design.mood_board||"—")+'</div>'+
        '</div></div>';
    // Business-day timing is NOT used here: milestone lead times and this
    // variance are calendar days. UTC-midnight avoids local DST shifts.
    const dayNumber = value => {
        if(typeof value!=="string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
            return null;
        const stamp=Date.parse(value+"T00:00:00Z");
        return Number.isFinite(stamp) &&
            new Date(stamp).toISOString().slice(0,10)===value ?
            Math.round(stamp/86400000):null;
    };
    const varianceHTML = row => {
        if(row.plan_state!=="Completed" || row.status!=="Completed")
            return "—";
        const projected=dayNumber(row.projected_due_date);
        const completed=dayNumber(row.completion_date);
        if(projected===null || completed===null)return "—";
        const difference=completed-projected;
        if(difference<0)
            return '<span class="text-success font-weight-bold">'+
                esc(__("Earlier {0} days",[Math.abs(difference)]))+'</span>';
        if(difference>0)
            return '<span class="text-danger font-weight-bold">'+
                esc(__("Overdue {0} days",[difference]))+'</span>';
        return '<span class="text-muted font-weight-medium">'+
            esc(__("On Time"))+'</span>';
    };
    const milestoneCells = (design,row,di,mi,includeDesign) => {
        const selectable=bulkEnabled() && bulkEligible(row);
        const bulkCell=bulkEnabled()?
            '<td class="text-center" style="width:38px">'+
            '<input type="checkbox" class="mdm-bulk-row" data-design="'+di+
            '" data-milestone="'+mi+'" aria-label="'+esc(__("Select for bulk completion"))+'" '+
            (selectable?'':'disabled ')+
            (state.selectedBulk.has(row.execution)?'checked ':'')+'></td>':'';
        const dirty=state.dirty.get(row.execution);
        const currentNote=dirty?dirty.note:(row.note||"");
        const note=row.can_note && row.execution?
            '<textarea class="form-control input-sm mdm-grid-note" data-design="'+di+
            '" data-milestone="'+mi+'" rows="2" maxlength="500" '+
            'style="min-width:170px;max-width:310px">'+esc(currentNote)+'</textarea>':
            '<span class="small" style="white-space:pre-wrap">'+esc(currentNote||"—")+'</span>';
        const steps=(row.allowed_steps||[]).map(step=>
            '<button type="button" class="btn btn-default btn-xs mdm-grid-step mr-1 mb-1" '+
            'data-design="'+di+'" data-milestone="'+mi+'" data-step="'+esc(step)+'">'+
            esc(actionLabel(row.status,step))+'</button>').join("");
        const evidence=row.evidence_document && row.evidence_accessible?
            (row.evidence_download_url?
                '<a href="'+esc(row.evidence_download_url)+'" download '+
                'title="'+esc(__("Download evidence file"))+'">'+
                esc(row.evidence_title||row.evidence_document)+'</a>':
                '<span title="'+esc(__("No downloadable attachment"))+'">'+
                esc(row.evidence_title||row.evidence_document)+'</span>'):
            (row.evidence_document?__('Restricted document'):'—');
        return '<tr>'+bulkCell+
            (includeDesign?'<td style="min-width:225px">'+designIdentityHTML(design,di)+'</td>':'')+
            '<td style="min-width:155px">'+esc(row.milestone_type)+'</td>'+
            '<td class="'+statusClass(row)+'">'+esc(row.status)+'</td>'+
            '<td>'+note+'</td>'+
            '<td style="white-space:nowrap">'+esc(row.projected_due_date||"—")+'</td>'+
            '<td style="white-space:nowrap">'+esc(row.completion_date||"—")+'</td>'+
            '<td style="white-space:nowrap">'+varianceHTML(row)+'</td>'+
            '<td style="min-width:150px">'+
                '<div class="font-weight-bold">'+esc(row.custodian_title||"—")+'</div>'+
                '<div class="small text-info">'+esc(row.current_role||"—")+'</div>'+
            '</td>'+
            '<td>'+evidence+'</td>'+
            '<td style="min-width:155px">'+(steps||'—')+'</td>'+
            '</tr>';
    };
    const designRowsHTML = (design,di) => {
        const expanded=state.expanded.has(design.name);
        const completed=design.milestones.filter(r=>r.status==="Completed" &&
            r.plan_state==="Completed").length;
        const active=design.milestones.filter(r=>r.plan_state==="Active").length;
        const total=design.milestones.length;
        // The server calculates progress from frozen per-milestone effort.
        // Completed parallel milestones earn weight independently; due dates
        // and workflow timing never change the weight after planning.
        const completion=Number.isInteger(design.completion_percent)?
            design.completion_percent:null;
        const completionText=!total?__("Not initialized"):
            completion===null?__("Completion unavailable"):
            __("{0}% complete",[completion]);
        const tooltip=completion===null?
            __("Completion weights are unavailable; review milestone plans"):
            __("Completed milestone effort: {0} of {1} planned weight days. Each completed milestone contributes independently.",[
                design.baseline_earned_days,design.baseline_total_days
            ]);
        const label=expanded?__("Collapse milestones"):__("Expand milestones");
        const arrow=expanded?"▾":"▸";
        let html='<tr class="table-active mdm-design-header"><td colspan="'+
            (bulkEnabled()?10:9)+'">'+
            '<div class="d-flex align-items-center">'+
            '<button type="button" class="btn btn-default btn-sm mdm-toggle-design mr-2" '+
            'data-design="'+di+'" aria-expanded="'+expanded+'" aria-label="'+esc(label)+'" '+
            'title="'+esc(label)+'">'+arrow+'</button>'+
            imageHTML(design)+'<div><div class="d-flex align-items-center flex-wrap" '+
            'style="gap:8px">'+designTitleHTML(design,di)+
            '<span class="small font-weight-bold text-muted mdm-design-progress" '+
            'title="'+esc(tooltip)+'">'+
            esc(completionText)+'</span></div>'+
            '<div class="small text-muted">'+__("Mood Board")+': '+
            esc(design.mood_board||"—")+'</div>'+
            '<div class="small text-muted">'+
            __("{0} milestones · {1} active · {2} completed",[
                design.milestones.length,active,completed])+
            '</div></div></div></td></tr>';
        if(!expanded)return html;
        if(!design.milestones.length){
            return html+'<tr><td colspan="'+(bulkEnabled()?10:9)+'" class="text-muted">'+
                __("No milestone plan selected for this Design.")+'</td></tr>';
        }
        let shown=0;
        design.milestones.forEach((row,mi)=>{
            if (!showMilestone(row))return;
            shown++;
            html+=milestoneCells(design,row,di,mi,false);
        });
        if (!shown) html+='<tr><td colspan="'+(bulkEnabled()?10:9)+'" class="text-muted">'+
            __("No milestones match this filter for this Design.")+'</td></tr>';
        return html;
    };
    const groupedRowsHTML = (designs,view) => {
        // Group the already permission-filtered, paginated batch in memory.
        // Key by User ID (not display name) to avoid merging different users.
        const groups=new Map();
        designs.forEach((design,di)=>{
            (design.milestones||[]).forEach((row,mi)=>{
                if(!showMilestone(row))return;
                const key=view==="milestone"?row.milestone_type:
                    (row.current_custodian||"");
                if(!groups.has(key))groups.set(key,{
                    title:view==="milestone"?row.milestone_type:
                        (row.custodian_title||__("Unassigned / Future")),
                    sequence:row.sequence||0,
                    entries:[]
                });
                groups.get(key).entries.push({design,row,di,mi});
            });
        });
        const entries=[...groups.entries()].sort((a,b)=>
            view==="milestone"?
                (Number(a[1].sequence)-Number(b[1].sequence) ||
                 a[1].title.localeCompare(b[1].title)):
                (a[0]===""?1:b[0]===""?-1:
                 a[1].title.localeCompare(b[1].title)));
        return entries.map(([key,group])=>{
            const heading='<tr class="table-active mdm-group-header"><td colspan="'+
                (bulkEnabled()?11:10)+'">'+
                '<strong>'+esc(group.title)+'</strong> '+
                '<span class="text-muted">('+group.entries.length+' '+__("milestones on this page")+')</span>'+
                '</td></tr>';
            return heading+group.entries.map(({design,row,di,mi})=>
                milestoneCells(design,row,di,mi,true)).join("");
        }).join("");
    };
    const draw = () => {
        const data=state.data;
        if(!data)return;
        const designs=allRows();
        const flatCount=designs.reduce((sum,d)=>
            sum+d.milestones.filter(showMilestone).length,0);
        const grouped=state.view!=="design";
        const groupName=state.view==="milestone"?__("Milestone"):
                        state.view==="user"?__("User (Custodian)"):__("Design Code");
        expandAll.toggle(!grouped);
        collapseAll.toggle(!grouped);
        number.add(footerNumber).text(__("Page")+" "+data.page);
        prev.add(footerPrev).prop("disabled",data.page<=1);
        next.add(footerNext).prop("disabled",!data.has_more);
        footer.show();
        info.text(__("Grouped by {0} (current page)",[groupName])+" · "+
            designs.length+" "+__("designs on this page")+" · "+
            flatCount+" "+__("milestones"));
        const headers=(bulkEnabled()?[__("Select")]:[])
            .concat(grouped?[__("Design")]:[]).concat([
            __("Milestone"),__("Status"),__("Notes"),
            __("Projected Due"),__("Completion Date"),__("Variance"),
            __("Custody / Role"),__("Evidence"),__("Actions")
        ]);
        const body=designs.length?
            (grouped?(groupedRowsHTML(designs,state.view) ||
                '<tr><td colspan="'+headers.length+'" class="text-muted">'+
                __("No milestones match this filter on the current page.")+'</td></tr>'):
                designs.map(designRowsHTML).join("")):
            '<tr><td colspan="'+headers.length+'" class="text-muted">'+
            __("No matching Design Codes.")+'</td></tr>';
        surface.html('<table class="mdm-grid-table table table-bordered table-hover table-sm" '+
            'style="vertical-align:middle">'+
            '<thead class="thead-light"><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join("")+
            '</tr></thead><tbody>'+body+'</tbody></table>');
        changeButton();
        updateBulkActions();
    };
    const reload = () => {
        const token=++state.request;
        const args={page:state.page,page_size:Number(size.val()),
                    search:search.val().trim(),
                    design_codes:state.designCodes.length?JSON.stringify(state.designCodes):null,
                    mood_board:mood.get_value(),
                    designer:designer.get_value(),factory:factory.val(),
                    season:hierarchyFilters.season.val(),
                    collection:hierarchyFilters.collection.val(),
                    milestone_type:milestoneType.val()||null,
                    custody:custody.get_value(),
                    milestone_view:state.milestoneFilter,
                    dashboard_milestone:state.dashboard?.milestone||null,
                    ...(state.dashboard?.filters||{})};
        // Render an actionable error instead of a blank table when a
        // permission, migration or request failure prevents grid loading.
        Promise.resolve(endpoint("followup_grid",args)).then(data=>{
            if(token!==state.request)return;
            if(!data || !Array.isArray(data.designs)){
                throw new Error("Invalid Follow-Up Grid response");
            }
            state.data=data;
            state.selectedBulk.clear();
            state.appliedCustody=args.custody||"";
            state.selectedMilestone=args.milestone_type||"";
            if(state.dashboard){
                data.designs.forEach(design=>state.expanded.add(design.name));
            }
            draw();
        }).catch(error=>{
            if(token!==state.request)return;
            state.data=null;
            info.text(__("Unable to load the Follow-Up Grid"));
            surface.html(
                '<div class="alert alert-warning" role="alert">'+
                '<strong>'+esc(__("Follow-Up Grid could not be loaded."))+'</strong> '+
                esc(__("Check your permissions and site migration, then use Refresh to retry."))+
                '</div>'
            );
            console.error("Marina Follow-Up Grid request failed",error);
        });
    };
    function reviewStep(design,row,step){
        const requiredType=row.evidence_types?.[step]||null;
        dirtyGuard(()=>{
            const dialog=new frappe.ui.Dialog({
                title:__("Move {0} to {1}",[row.milestone_type,step]),
                fields:[
                    {fieldname:"step_change_date",label:__("Step Change Date"),
                     fieldtype:"Date",reqd:1,default:frappe.datetime.get_today(),
                     description:__("Effective date of this step. The system keeps the actual recording time in the audit history.")},
                    {fieldname:"reason",label:__("Reason / Review Notes"),fieldtype:"Small Text",
                     reqd:step==="Rework"?1:0,
                     description:__("A reason is required for rework and manager overrides.")},
                    {fieldname:"evidence_document",label:__("Published Evidence"),
                     fieldtype:"Link",options:"Design Document",
                     hidden:requiredType?0:1,reqd:requiredType?1:0,
                     description:requiredType
                         ? __("Choose a Published document. If not yet linked, confirm its assignment to this Design and milestone before completing the step.")
                         : __("Evidence is not required for this step."),
                     get_query:()=>({
                         query:"marina_custom_apps.design_management.clean_milestones.evidence.search_milestone_evidence",
                         filters:{design_code:design.name,
                                  milestone_type:row.milestone_type,step:step}
                     })},
                ],
                primary_action_label:actionLabel(row.status,step),
                primary_action(values){
                    const submit=confirmed=>endpoint("advance_step",{
                        design_code:design.name,execution_name:row.execution,
                        next_step:step,reason:values.reason,
                        step_change_date:values.step_change_date,
                        evidence_document:values.evidence_document,
                        confirm_evidence_link:confirmed?1:0
                    },true).then(()=>{dialog.hide();reload()});
                    if(!requiredType || !values.evidence_document){
                        submit(false);return;
                    }
                    frappe.call({
                        method:"marina_custom_apps.design_management.clean_milestones.evidence.preview_evidence_link",
                        args:{design_code:design.name,milestone_type:row.milestone_type,
                              document_name:values.evidence_document,step:step}
                    }).then(({message:details})=>{
                        if(!details ||
                                dialog.get_value("evidence_document")!==values.evidence_document)return;
                        if(!details.requires_confirmation){submit(false);return;}
                        const mismatch=details.document_milestone &&
                            details.document_milestone!==row.milestone_type;
                        const warning=mismatch
                            ? __("The document is labeled for milestone {0}, but you are linking it to {1}. Verify the file is appropriate before approving.",[
                                esc(details.document_milestone),
                                esc(row.milestone_type)])
                            : "";
                        frappe.confirm(
                            __("Link Published document {0} ({1}) to Design {2} / Milestone {3}, and complete this step? The existing document file will not change.",[
                                esc(details.document_title||details.document),
                                esc(details.document),
                                esc(design.name),
                                esc(row.milestone_type)
                            ])+" "+warning,
                            ()=>submit(true)
                        );
                    });
                }
            });
            dialog.show();
        });
    }
    function bulkPageRows(){
        return allRows().flatMap(design=>(design.milestones||[])
            .filter(row=>showMilestone(row) && bulkEligible(row))
            .map(row=>({design_code:design.name,execution:row.execution,row})));
    }
    const selectedPayload=()=>[...state.selectedBulk.values()].map(item=>({
        design_code:item.design_code,execution:item.execution
    }));
    function addBulkRow(item){
        if(state.selectedBulk.has(item.execution))return true;
        if(state.selectedBulk.size>=50){
            frappe.msgprint(__("Select no more than 50 milestone rows per batch."));
            return false;
        }
        const chosen=[...state.selectedBulk.values()];
        if(chosen.some(existing=>existing.design_code===item.design_code)){
            frappe.msgprint(__("Select only one milestone per Design Code."));
            return false;
        }
        state.selectedBulk.set(item.execution,item);
        return true;
    }
    bulkAll.on("click",()=>dirtyGuard(()=>{
        if(!bulkEnabled())return;
        const rows=bulkPageRows();
        if(!rows.length){
            frappe.msgprint(__("No eligible milestones found on this page."));
            return;
        }
        const additional=rows.filter(item=>!state.selectedBulk.has(item.execution));
        const codes=new Set([...state.selectedBulk.values()].map(item=>item.design_code));
        const uniqueAdditional=additional.filter(item=>{
            if(codes.has(item.design_code))return false;
            codes.add(item.design_code);
            return true;
        });
        if(state.selectedBulk.size+uniqueAdditional.length>50){
            frappe.msgprint(__("This selection exceeds 50 designs. Reduce Designs / Page or select individual rows."));
            return;
        }
        uniqueAdditional.forEach(item=>addBulkRow(item));
        draw();
    }));
    surface.on("change",".mdm-bulk-row",function(){
        if(!bulkEnabled())return;
        const design=allRows()[Number($(this).attr("data-design"))];
        const row=design?.milestones?.[Number($(this).attr("data-milestone"))];
        if(!design||!row||!bulkEligible(row))return;
        if($(this).prop("checked")){
            addBulkRow({design_code:design.name,execution:row.execution,row});
        }else{
            state.selectedBulk.delete(row.execution);
        }
        draw();
    });
    bulkComplete.on("click",()=>dirtyGuard(async()=>{
        if(!bulkEnabled()||!state.selectedBulk.size)return;
        const selected=selectedPayload();
        // Preview is read-only; the server checks the full authorization and
        // source-of-truth state again before the transactional POST.
        let preview;
        try{
            preview=await endpoint("preview_bulk_completion",{
                selected:JSON.stringify(selected),reason:"Bulk milestone completion"
            });
        }catch(error){
            frappe.msgprint(__("Bulk selection cannot be completed. Check milestone, step, custody and user permissions."));
            return;
        }
        if(!preview || preview.count!==selected.length)return;
        const documentRequired=Boolean(preview.evidence_type);
        const evidenceChoices=(preview.evidence_options||[]).map(doc=>({
            name:doc.name,
            display:(doc.title||doc.name)+" ("+doc.name+")"
        }));
        const documentByDisplay=new Map(evidenceChoices.map(doc=>[doc.display,doc.name]));
        const dialog=new frappe.ui.Dialog({
            title:__("Complete {0} selected designs",[preview.count]),
            fields:[
                {fieldtype:"HTML",fieldname:"summary_html"},
                {fieldtype:"Date",fieldname:"step_change_date",
                 label:__("Completion Date"),reqd:1,
                 default:frappe.datetime.get_today(),
                 description:__("Same effective completion date for every selected milestone.")},
                {fieldtype:"Small Text",fieldname:"reason",
                 label:__("Reason / Review Notes"),
                 default:"Bulk milestone completion",
                 description:__("A reason may be required for manager override or correction.")},
                {fieldtype:"Select",fieldname:"evidence_document",
                 label:__("Published Evidence"),
                 options:["",...evidenceChoices.map(doc=>doc.display)],
                 hidden:documentRequired?0:1,
                 reqd:documentRequired?1:0,
                 description:documentRequired?
                     __("Select one Published Fitting Report or other milestone evidence. The same document is linked to all selected designs."):
                     __("This milestone does not require evidence.")}
            ],
            primary_action_label:__("Complete All Selected"),
            async primary_action(values){
                if(!values.step_change_date)return;
                const names=preview.design_codes.map(code=>esc(code)).join(", ");
                const documentText=documentRequired?
                    __("The Published Evidence will be linked to all designs."):"";
                frappe.confirm(
                    __("Complete {0} designs at milestone {1} from step {2} for custodian {3}? Designs: {4}",[
                        preview.count,esc(preview.milestone_type),
                        esc(preview.current_step),esc(preview.custodian),names
                    ])+" "+documentText,
                    async()=>{
                        try {
                            const result=await endpoint("complete_bulk_milestones",{
                                selected:JSON.stringify(selected),
                                evidence_document:documentByDisplay.get(values.evidence_document)||null,
                                step_change_date:values.step_change_date,
                                reason:values.reason||"",
                                confirm_evidence_link:documentRequired?1:0
                            },true);
                            dialog.hide();
                            state.selectedBulk.clear();
                            frappe.show_alert({
                                indicator:"green",
                                message:__("Completed {0} milestones",[result.completed])
                            },8);
                            reload();
                        }catch(error){
                            console.error("Bulk completion failed",error);
                            frappe.msgprint(__("No milestones were completed. Review the error and retry."));
                        }
                    }
                );
            }
        });
        dialog.show();
        dialog.fields_dict.summary_html.$wrapper.html(
            '<p><b>'+esc(preview.milestone_type)+'</b> — '+
            esc(preview.current_step)+' — '+esc(preview.custodian)+'</p>'+
            '<p>'+esc(__("{0} designs selected",[preview.count]))+'</p>'+
            '<div style="max-height:130px;overflow:auto">'+
            preview.design_codes.map(code=>'<span class="badge badge-light mr-1 mb-1">'+
                esc(code)+'</span>').join("")+'</div>'+
            (documentRequired?'<p class="small text-muted">'+
                esc(__("Required evidence type: {0}",[preview.evidence_type]))+
                ' · '+esc(__("{0} Published documents available",[
                    (preview.evidence_options||[]).length]))+'</p>':"")
        );
    }));
    surface.on("click",".mdm-toggle-design",function(){
        const design=allRows()[Number($(this).attr("data-design"))];
        if(!design)return;
        if(state.expanded.has(design.name))state.expanded.delete(design.name);
        else state.expanded.add(design.name);
        draw(); // Note edits remain in state.dirty even if hidden.
    });
    surface.on("click", ".mdm-design-discussion", function() {
        const design = allRows()[Number($(this).attr("data-design"))];
        if (design) marina.discussions.open("Design Code", design.name);
    });

    // Audit history is fetched on demand, never once per grid row.
    surface.on("click",".mdm-design-history",function(){
        const design=allRows()[Number($(this).attr("data-design"))];
        if(!design)return;
        const dialog=new frappe.ui.Dialog({
            title:__("Workflow History: {0}",[design.name]),size:"extra-large",
            fields:[{fieldname:"history",fieldtype:"HTML"}]
        });
        const body=dialog.fields_dict.history.$wrapper;
        let offset=0,busy=false;
        const rows=$('<div class="table-responsive"></div>').appendTo(body);
        const footer=$('<div class="d-flex align-items-center mt-3"></div>')
            .css("gap","12px").appendTo(body);
        const previous=$('<button type="button" class="btn btn-default btn-sm"></button>')
            .text(__("Previous")).appendTo(footer);
        const nextHistory=$('<button type="button" class="btn btn-default btn-sm"></button>')
            .text(__("Next")).appendTo(footer);
        const label=$('<span class="text-muted"></span>').appendTo(footer);
        const loadHistory=(start)=>{
            if(busy)return;
            busy=true;previous.prop("disabled",true);nextHistory.prop("disabled",true);
            rows.text(__("Loading history..."));
            // One extra row determines whether another page exists.
            Promise.resolve(endpoint("history",{
                design_code:design.name,offset:start,limit:51
            })).then(events=>{
                offset=start;
                const columns=[__("Date"),__("Effective Date"),__("Milestone"),
                    __("Action"),__("By"),__("From"),__("To"),
                    __("Previous Custodian"),__("New Custodian"),__("Reason")];
                rows.html(events.length?'<table class="table table-bordered table-sm"><thead><tr>'+
                    columns.map(x=>'<th>'+esc(x)+'</th>').join("")+'</tr></thead><tbody>'+
                    events.slice(0,50).map(x=>'<tr>'+[
                        x.performed_on,x.effective_date,x.milestone_type,x.action,
                        x.performed_by_username,x.from_status,x.to_status,
                        x.from_user_username,x.to_user_username,x.reason
                    ].map(v=>'<td style="white-space:pre-wrap">'+esc(v||"—")+'</td>').join("")+
                    '</tr>').join("")+'</tbody></table>':esc(__("No workflow history.")));
                label.text(__("Page")+" "+(offset/50+1));
                previous.prop("disabled",offset===0);
                nextHistory.prop("disabled",events.length<=50);
            }).catch(()=>{
                rows.text(__("History could not be loaded. Close and reopen History to retry."));
            }).finally(()=>{busy=false;});
        };
        previous.on("click",()=>loadHistory(Math.max(0,offset-50)));
        nextHistory.on("click",()=>loadHistory(offset+50));
        dialog.show();loadHistory(0);
    });
    surface.on("click",".mdm-open-design",function(e){
        e.preventDefault();
        const d=allRows()[Number($(this).attr("data-design"))];
        if(d)dirtyGuard(()=>frappe.set_route("Form","Design Code",d.name));
    });
    surface.on("click",".mdm-grid-step",function(){
        const d=allRows()[Number($(this).attr("data-design"))];
        const r=d?.milestones?.[Number($(this).attr("data-milestone"))];
        if(d&&r)reviewStep(d,r,$(this).attr("data-step"));
    });
    surface.on("input",".mdm-grid-note",function(){
        const di=Number($(this).attr("data-design"));
        const mi=Number($(this).attr("data-milestone"));
        const d=allRows()[di],r=d?.milestones?.[mi];
        if(!r?.can_note || !r.execution)return;
        const value=$(this).val();
        if(value===(r.note||""))state.dirty.delete(r.execution);
        else state.dirty.set(r.execution,{design_code:d.name,execution:r.execution,
            expected_note:r.note||"",note:value});
        changeButton();
    });
    save.on("click",()=>{
        const edits=[...state.dirty.values()];
        if(!edits.length)return;
        if(edits.length>50){
            frappe.msgprint(__("Save up to 50 milestone notes at a time."));return;
        }
        if(edits.some(r=>r.note.trim().length<1 || r.note.trim().length>500)){
            frappe.msgprint(__("Each edited note must have 1–500 characters."));return;
        }
        endpoint("save_followup_notes",{changes:edits},true).then(result=>{
            frappe.show_alert({indicator:"green",
                message:__("Saved {0} notes",[result?.saved||0])});
            state.dirty.clear();reload();
        });
    });
    milestoneFilter.on("change",()=>{
        if(state.dashboard){milestoneFilter.val(state.milestoneFilter);return;}
        const next=milestoneFilter.val();
        if(!state.appliedCustody){
            state.selectedBulk.clear();
            // With no Custody filtering, all milestone states are already
            // loaded; retain the original zero-query in-memory behavior.
            state.milestoneFilter=next;
            draw();
            return;
        }
        const previous=state.milestoneFilter;
        const change=()=>{
            state.selectedBulk.clear();
            state.milestoneFilter=next;
            milestoneFilter.val(next);
            state.page=1;
            reload(); // Custody pagination must match the selected state.
        };
        if(!state.dirty.size){change();return;}
        milestoneFilter.val(previous);
        frappe.confirm(__("Discard unsaved milestone notes?"),()=>{
            state.dirty.clear();changeButton();change();
        });
    });
    groupBy.on("change",()=>{
        const selected=groupBy.val();
        if(selected===state.view)return;
        const applyView=()=>{
            state.view=selected;
            groupBy.val(selected);
            draw(); // In-memory regrouping; no new server request.
        };
        if(!state.dirty.size){
            applyView();
            return;
        }
        // If the user cancels discarding unsaved notes, restore the Select
        // control too, so it cannot disagree with the displayed grouping.
        groupBy.val(state.view);
        frappe.confirm(__("Discard unsaved milestone notes?"),()=>{
            state.dirty.clear();
            changeButton();
            applyView();
        });
    });
    expandAll.on("click",()=>{
        allRows().forEach(d=>state.expanded.add(d.name));
        draw();
    });
    collapseAll.on("click",()=>{
        allRows().forEach(d=>state.expanded.delete(d.name));
        draw();
    });
    apply.on("click",()=>dirtyGuard(()=>{state.page=1;reload()}));
    refresh.on("click",()=>dirtyGuard(()=>reload()));
    clearDashboard.on("click",()=>dirtyGuard(()=>{
        frappe.set_route("design-followup-grid");
    }));
    size.on("change",()=>dirtyGuard(()=>{state.page=1;reload()}));
    search.on("keydown",e=>{if(e.key==="Enter"){e.preventDefault();apply.trigger("click")}});
    prev.on("click",()=>dirtyGuard(()=>{if(state.page>1){state.page--;reload()}}));
    next.on("click",()=>dirtyGuard(()=>{
        if(state.data?.has_more){state.page++;reload()}
    }));
    function selectPlan(design){
        endpoint("available_milestones",{design_code:design}).then(types=>{
            if(!types?.length){
                frappe.msgprint(__("No enabled milestones found in the master."));
                return;
            }
            const creationDate=types[0].design_creation_date;
            const values=Object.fromEntries(types.map(t=>[
                t.name,Number(t.default_lead_days||0)]));
            const dialog=new frappe.ui.Dialog({
                title:__("Create Milestones for this Design"),size:"large",
                fields:[{fieldname:"selection",fieldtype:"HTML"}],
                primary_action_label:__("Create Plan"),
                primary_action(){
                    const selected=types.map(t=>t.name);
                    const overrides={};
                    let invalid=false;
                    selected.forEach(name=>{
                        const entry=dialog.fields_dict.selection.$wrapper
                            .find("input.mdm-plan-lead")
                            .filter((_,el)=>el.dataset.name===name);
                        const raw=String(entry.val()||"").trim();
                        const days=Number(raw);
                        if(!/^\d+$/.test(raw)||!Number.isInteger(days)||days>3650){
                            invalid=true;
                        }else overrides[name]=days;
                    });
                    if(invalid){
                        frappe.msgprint(__("Lead Time must be a whole number from 0 to 3650."));
                        return;
                    }
                    const projected=marinaProjectDesignPlan(
                        types,new Set(selected),overrides,creationDate);
                    if(selected.some(name=>!projected[name]?.due)){
                        frappe.msgprint(__("Active milestones must have valid dependencies and projected dates. Ask your administrator to review Milestone Master."));
                        return;
                    }
                    dialog.get_primary_btn().prop("disabled",true);
                    Promise.resolve(endpoint("create_plan",{
                        design_code:design,milestone_types:selected,
                        lead_time_overrides:overrides
                    },true)).then(()=>{dialog.hide();reload();}).catch(()=>{
                        dialog.get_primary_btn().prop("disabled",false);
                    });
                }
            });
            dialog.show();
            const rows=types.map((t,index)=>{
                const single=(t.workflow_steps||[]).length===1;
                return '<div class="border-bottom p-2" style="display:grid;'+
                    'grid-template-columns:minmax(255px,1fr) 104px 130px;gap:12px;align-items:center">'+
                    '<div style="margin:0;min-width:0">'+
                    '<b>'+esc(t.name)+'</b> <small class="text-muted">'+
                    esc(t.start_with_design_creation?__("Start with Design Creation"):
                        ((t.depends_on_type||"—")+" → "+(t.r22_trigger_status||"Completed")))+
                    '</small></div>'+
                    '<input type="number" class="form-control input-sm mdm-plan-lead" '+
                    'data-name="'+esc(t.name)+'" min="0" max="3650" step="1" '+
                    'aria-label="'+esc(__("Lead Time Days")+" - "+t.name)+'" '+
                    'value="'+Number(t.default_lead_days||0)+'" '+(single?'disabled ':'')+'/>'+
                    '<span class="mdm-plan-date small" data-index="'+index+'">—</span></div>';
            }).join("");
            const container=dialog.fields_dict.selection.$wrapper;
            container.html('<p class="text-muted small">'+
                __("All active milestones are required. Edit lead times below. Planning baseline: Design Code creation date {0}. Changes apply only to this Design, not to Milestone Master.",[creationDate])+
                '</p><div style="display:grid;grid-template-columns:minmax(255px,1fr) 104px 130px;'+
                'gap:12px;font-weight:600" class="border-bottom pb-2"><span>'+__("Milestone")+
                '</span><span>'+__("Lead Time Days")+'</span><span>'+__("Projected Due Date")+
                '</span></div><div style="max-height:380px;overflow:auto">'+rows+'</div>');
            const recalculate=()=>{
                const selected=new Set(types.map(t=>t.name));
                let invalid=false;
                container.find("input.mdm-plan-lead").each((_,el)=>{
                    const raw=String(el.value||"").trim();
                    if(!/^\d+$/.test(raw)||Number(raw)>3650){
                        if(selected.has(el.dataset.name))invalid=true;
                    }else values[el.dataset.name]=Number(raw);
                });
                const dates=marinaProjectDesignPlan(types,selected,values,creationDate);
                types.forEach((t,i)=>{
                    const due=dates[t.name]?.due;
                    container.find('.mdm-plan-date[data-index="'+i+'"]')
                        .text(due?(frappe.datetime.str_to_user(due)||due):"—");
                });
                const missing=[...selected].some(name=>!dates[name]?.due);
                const btn=dialog.get_primary_btn?.();
                if(btn?.prop)btn.prop("disabled",invalid||missing||!selected.size);
            };
            container.on("input change","input.mdm-plan-lead",recalculate);
            recalculate();
        });
    }

    // When opened from a Design Code, display that Design only; users may
    // still edit/clear the Search box and apply other filters normally.
    // The page object is cached by Frappe, so repeat this when shown again.
    let custodyReady=false;
    wrapper.marina_sync_design_route=(force=false)=>{
        if(!custodyReady)return;
        const route=frappe.get_route();
        if(route[0]!=="design-followup-grid")return;
        const selected=route[1]||"";
        const signature=route.join("|");
        if(!force && wrapper.__marina_route_design===signature)return;
        wrapper.__marina_route_design=signature;
        const next=()=>{
            if(selected==="dashboard"){
                try {
                    const view=route[2];
                    const milestone=decodeURIComponent(route[3]||"");
                    const filters=JSON.parse(decodeURIComponent(route[4]||"%7B%7D"));
                    const accepted=["year","season","collection","drop","mood_board",
                                    "assigned_merchandiser","deadline_status","current_milestone"];
                    if(!["active","completed"].includes(view) ||
                            !milestone || milestone.length>140 ||
                            !filters || Array.isArray(filters) ||
                            typeof filters!=="object" ||
                            Object.keys(filters).some(key=>!accepted.includes(key) ||
                                typeof filters[key]!=="string" ||
                                filters[key].length>140)){
                        throw new Error("Invalid dashboard filter");
                    }
                    state.dashboard={milestone,filters};
                    clearDashboard.show();
                    state.milestoneFilter=view;
                    milestoneFilter.val(view).prop("disabled",true);
                    state.designCodes=[];showMultiCount();
                    search.val("");factory.val("");
                    ["season","collection"].forEach(key=>
                        hierarchyFilters[key].val(filters[key]||""));
                    milestoneType.data("pending-value",milestone).val(milestone).prop("disabled",true);
                    state.page=1;
                    state.view="design";groupBy.val("design");
                    Promise.all([mood.set_value(filters.mood_board||""),
                        designer.set_value(""),custody.set_value("")]).then(()=>{
                        if(frappe.get_route().join("|")!==signature)return;
                        reload();
                    });
                } catch(error){
                    frappe.msgprint(__("Invalid dashboard drill-down. Open the dashboard again."));
                }
                return;
            }
            state.dashboard=null;
            clearDashboard.hide();
            milestoneFilter.prop("disabled",false);
            milestoneType.prop("disabled",false);
            search.val(selected);
            state.designCodes=[];
            showMultiCount();
            state.page=1;
            if(!selected){reload();return;}
            factory.val("");
            // Clear cached filters that could hide the requested design.
            Promise.all([mood.set_value(""),designer.set_value(""),custody.set_value("")])
                .then(()=>{
                    if(frappe.get_route()[1]!==selected)return;
                    state.expanded.add(selected);
                    state.view="design";groupBy.val("design");
                    reload();
                });
        };
        if(state.dirty.size)dirtyGuard(next);
        else next();
    };
    // Keep Create Milestones on the same page, with fresh permission checks.
    wrapper.marina_open_plan_from_route=()=>{
        const parts=frappe.get_route();
        if(parts[0]!=="design-followup-grid" ||
                parts[2]!=="create-milestones" || !parts[1])return;
        const design=parts[1], token=parts.join("|");
        if(wrapper.__marina_plan_launch_token===token)return;
        wrapper.__marina_plan_launch_token=token;
        Promise.resolve(endpoint("overview",{design_code:design})).then(data=>{
            if(frappe.get_route().join("|")!==token)return;
            if(!data.can_plan){
                frappe.msgprint(__("This Design already has a milestone plan, or your role cannot create it."));
            }else if(data.requires_main_image){
                frappe.msgprint(__("Attach Main Image and save this Design Code before creating milestones."));
            }else{selectPlan(design);}
        }).catch(()=>{wrapper.__marina_plan_launch_token=null;});
    };
    wrapper.marina_open_plan_from_route();
    // Start with all visible designs. Designer and Custody are optional
    // filters; users can select themselves via "Assigned to Me".
    custodyReady=true;
    wrapper.marina_sync_design_route();
};
frappe.pages["design-followup-grid"].on_page_show = function(wrapper) {
    wrapper.marina_sync_design_route?.(true);
    wrapper.marina_open_plan_from_route?.();
};




