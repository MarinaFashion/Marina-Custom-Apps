frappe.pages["design-management-dashboard"].on_page_load=function(wrapper){
    const page=frappe.ui.make_app_page({
        parent:wrapper,title:__("Design Management Dashboard"),single_column:true
    });
    page.add_inner_button(__("Refresh"),()=>refresh());
    const stageOptions=["Tech Pack Received","Material Sourcing","Sample 1","Sample 2",
                        "PPS Pending","PPS Approved","In Production"];
    const esc=frappe.utils.escape_html;
    const filter=(name,label,placeholder="")=>
        '<div class="col-md-3 mb-2"><label>'+esc(label)+'</label>'+
        '<input class="form-control" data-filter="'+esc(name)+'" placeholder="'+esc(placeholder)+'"></div>';
    page.main.html('<div class="container-fluid p-3 mdm-r4-dashboard"><div class="row">'+
        filter("year",__("Year"),"2027")+filter("season",__("Season"),"Summer")+
        filter("mood_board",__("Mood Board"))+
        filter("assigned_merchandiser",__("Merchandiser"))+
        '<div class="col-md-3 mb-2"><label>'+__("Development Stage")+'</label>'+
        '<select class="form-control" data-filter="development_stage"><option value="">'+
        __("All")+'</option>'+stageOptions.map(s=>'<option>'+esc(s)+'</option>').join("")+
        '</select></div><div class="col-md-3 mb-2"><label>'+__("Deadline Status")+'</label>'+
        '<select class="form-control" data-filter="deadline_status"><option value="">'+
        __("All")+'</option><option>Delayed</option><option>On Track</option></select></div>'+
        '<div class="col-md-2 pt-4"><button class="btn btn-primary btn-sm mdm-filter-apply">'+
        __("Apply Filters")+'</button></div></div>'+
        '<div class="mdm-summary mt-4"></div><div class="mdm-stage-distribution mt-4"></div></div>');
    page.main.find(".mdm-filter-apply").on("click",()=>refresh());
    function safe(value){return esc(String(value??""));}
    function refresh(){
        const filters={};
        page.main.find("[data-filter]").each((_,el)=>{
            if(el.value?.trim())filters[el.dataset.filter]=el.value.trim();
        });
        frappe.call({
            method:"marina_custom_apps.design_management.api.dashboard.get_design_dashboard",
            args:filters,freeze:true,freeze_message:__("Loading design status...")
        }).then(({message:r})=>{
            if(!r)return;
            const cards=[[__("Active Designs"),r.total],[__("In Production"),r.in_production],
                [__("Delayed"),r.delayed],[__("Blocked / On Hold"),r.blocked_hold],
                [__("Due within 7 days"),r.upcoming]];
            page.main.find(".mdm-summary").html('<div class="row">'+cards.map(([label,value])=>
                '<div class="col-md-2 mb-3"><div class="border rounded p-3"><div class="text-muted small">'+
                safe(label)+'</div><div class="h3 mt-2">'+safe(value)+'</div></div></div>'
            ).join("")+'</div>');
            const stages=r.stages||[];
            const max=Math.max(1,...stages.map(x=>Number(x.designs)||0));
            page.main.find(".mdm-stage-distribution").html(
                '<h4>'+__("Design Distribution by Stage")+'</h4>'+
                (stages.length?stages.map(x=>
                    '<div class="d-flex align-items-center mb-2">'+
                    '<div style="width:190px">'+safe(x.stage)+'</div>'+
                    '<div class="flex-fill bg-light rounded"><div class="bg-primary rounded" style="height:17px;width:'+
                    Math.max(0,Math.min(100,100*Number(x.designs)/max))+'%"></div></div>'+
                    '<b class="ml-3">'+safe(x.designs)+'</b></div>').join(""):
                    '<p class="text-muted">'+__("No Designs match these filters.")+'</p>'));
        });
    }
    refresh();
};
