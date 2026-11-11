frappe.pages["design-management-dashboard"].on_page_load=function(wrapper){
    const page=frappe.ui.make_app_page({
        parent:wrapper,title:__("Design Management Dashboard"),single_column:true
    });
    page.add_inner_button(__("Refresh"),()=>refresh());
    const esc=frappe.utils.escape_html;
    const hierarchyOptions={"season":["Ramadan","Summer","Winter"],"collection":["EID","Ramadan","Hajj","Summer","Autumn","Winter"],"drop":["Drop- 01","Drop- 02","Drop- 03","Drop- 04","Drop- B2S","Drop- Reorder","Not Assigned"]};
    const dropdown=(name,label)=>
        '<div class="col-md-3 mb-2"><label>'+esc(label)+'</label>'+
        '<select class="form-control" data-filter="'+esc(name)+'">'+
        '<option value="">'+__("All")+'</option>'+hierarchyOptions[name].map(value=>
            '<option value="'+esc(value)+'">'+esc(value)+'</option>').join("")+
        '</select></div>';
    const filter=(name,label,placeholder="")=>
        '<div class="col-md-3 mb-2"><label>'+esc(label)+'</label>'+
        '<input class="form-control" data-filter="'+esc(name)+'" placeholder="'+esc(placeholder)+'"></div>';
    page.main.html('<div class="container-fluid p-3 mdm-r4-dashboard"><div class="row">'+
        filter("year",__("Year"),"2027")+dropdown("season",__("Season"))+
        dropdown("collection",__("Collection"))+dropdown("drop",__("Drop"))+
        '<div class="col-md-3 mb-2"><label>'+__("Mood Board")+'</label>'+
        '<select class="form-control" data-filter="mood_board">'+
        '<option value="">'+__("All Mood Boards")+'</option></select></div>'+
        filter("assigned_merchandiser",__("Merchandiser"))+
        filter("current_milestone",__("Current Milestone"),__("Exact milestone name"))+
        '<div class="col-md-3 mb-2"><label>'+__("Deadline Status")+'</label>'+
        '<select class="form-control" data-filter="deadline_status"><option value="">'+
        __("All")+'</option><option>Delayed</option><option>On Track</option></select></div>'+
        '<div class="col-md-2 pt-4"><button class="btn btn-primary btn-sm mdm-filter-apply">'+
        __("Apply Filters")+'</button></div></div>'+
        '<div class="mdm-summary mt-4"></div>'+
        '<div class="mdm-current-distribution mt-4"></div>'+
        '<div class="mdm-completed-distribution mt-4"></div></div>');
    page.main.find(".mdm-filter-apply").on("click",()=>refresh());
    function safe(value){return esc(String(value??""));}
    const boardSelect=page.main.find('[data-filter="mood_board"]');
    let boardRequest=0;
    function loadMoodBoards(){
        const token=++boardRequest;
        const args={};
        ["year","season","collection","drop"].forEach(field=>{
            const value=page.main.find('[data-filter="'+field+'"]').val();
            if(value && String(value).trim())args[field]=String(value).trim();
        });
        const previous=boardSelect.val();
        boardSelect.prop("disabled",true);
        return frappe.call({
            method:"marina_custom_apps.design_management.api.dashboard.get_dashboard_mood_board_options",
            args
        }).then(({message:boards})=>{
            if(token!==boardRequest)return;
            boardSelect.empty().append($('<option></option>').val("").text(__("All Mood Boards")));
            (boards||[]).forEach(name=>
                boardSelect.append($('<option></option>').val(name).text(name)));
            boardSelect.val((boards||[]).includes(previous)?previous:"");
        }).catch(error=>{
            if(token!==boardRequest)return;
            console.error("Unable to load dashboard Mood Boards",error);
            frappe.show_alert({message:__("Unable to load Mood Board options"),indicator:"orange"});
        }).finally(()=>{
            if(token===boardRequest)boardSelect.prop("disabled",false);
        });
    }
    // Only reload choices when hierarchy filters change; no per-keystroke
    // queries and no unnecessary extra request on dashboard Refresh.
    page.main.find('[data-filter="year"],[data-filter="season"],'+
        '[data-filter="collection"],[data-filter="drop"]').on("change",loadMoodBoards);
    function chart(selector,title,rows,explanation,view){
        const max=Math.max(1,...rows.map(x=>Number(x.designs)||0));
        const bars=rows.map(x=>
            '<div class="d-flex align-items-center mb-2" style="gap:12px">'+
            '<div style="width:240px;flex:none;overflow-wrap:anywhere">'+
            '<a href="#" class="mdm-milestone-drilldown" data-view="'+safe(view)+'" '+
            'data-milestone="'+safe(x.milestone_type)+'">'+
            safe(x.milestone_type)+'</a></div>'+
            '<div class="flex-fill bg-light rounded">'+
            '<div class="rounded" style="background:#551C25;height:17px;width:'+
            Math.max(0,Math.min(100,100*Number(x.designs)/max))+'%"></div></div>'+
            '<b style="min-width:36px;text-align:right">'+safe(x.designs)+'</b></div>'
        ).join("");
        page.main.find(selector).html(
            '<h4>'+safe(title)+'</h4>'+
            '<p class="text-muted small">'+safe(explanation)+'</p>'+
            (rows.length?bars:'<p class="text-muted">'+
                __("No matching milestones.")+'</p>'));
    }
    // Drill into exactly the same visible dashboard selection. The grid
    // validates the status and applies these filters before pagination.
    page.main.on("click",".mdm-milestone-drilldown",function(event){
        event.preventDefault();
        const milestone=$(this).attr("data-milestone");
        const view=$(this).attr("data-view");
        if(!milestone || !["active","completed"].includes(view))return;
        const filters={};
        ["year","season","collection","drop","mood_board",
         "assigned_merchandiser","deadline_status","current_milestone"].forEach(field=>{
            const value=page.main.find('[data-filter="'+field+'"]').val();
            if(value && String(value).trim())filters[field]=String(value).trim();
        });
        frappe.set_route("design-followup-grid","dashboard",view,
            encodeURIComponent(milestone),
            encodeURIComponent(JSON.stringify(filters)));
    });
    let request=0;
    function refresh(){
        const token=++request;
        const filters={};
        page.main.find("[data-filter]").each((_,el)=>{
            if(el.value?.trim())filters[el.dataset.filter]=el.value.trim();
        });
        frappe.call({
            method:"marina_custom_apps.design_management.api.dashboard.get_design_dashboard",
            args:filters,freeze:true,freeze_message:__("Loading design status...")
        }).then(({message:r})=>{
            if(token!==request||!r)return;
            const cards=[
                [__("Total Designs"),r.total],
                [__("Average Completion"),safe(r.average_completion)+"%"],
                [__("Delayed Designs"),r.delayed],
                [__("Due within 7 days"),r.upcoming],
                [__("In Bulk Production"),r.in_bulk_production],
                [__("Blocked / On Hold"),r.blocked_hold]
            ];
            page.main.find(".mdm-summary").html('<div class="row">'+cards.map(([label,value])=>
                '<div class="col-lg-2 col-md-4 col-sm-6 mb-3"><div class="border rounded p-3">'+
                '<div class="text-muted small">'+safe(label)+'</div>'+
                '<div class="h3 mt-2">'+safe(value)+'</div></div></div>'
            ).join("")+'</div>');
            chart(".mdm-current-distribution",__("Designs by Current Milestone"),
                r.current_milestones||[],
                __("A Design may appear under multiple active milestones when work runs in parallel."),
                "active");
            chart(".mdm-completed-distribution",__("Designs by Completed Milestone"),
                r.completed_milestones||[],
                __("Number of designs that have completed each milestone."),
                "completed");
        }).catch(error=>{
            if(token!==request)return;
            console.error("Unable to load Design Management Dashboard",error);
            frappe.msgprint(__("Could not load dashboard. Check permissions and try Refresh."));
        });
    }
    loadMoodBoards();
    refresh();
};
