const ALLOWED_STORE_USER_QUERY =
  "marina_custom_apps.cycle_count.store_assignment.allowed_user_query";
const M="marina_custom_apps.cycle_count.doctype.cycle_count_plan.cycle_count_plan.get_filter_options", F=["item_year","season","collection","drop","main_group"];
frappe.ui.form.on("Cycle Count Plan",{onload(frm){configure_store_user_query(frm);rf(frm)},refresh(frm){configure_store_user_query(frm);if(frm.is_new())return;if(frm.doc.status!=="Counts Generated"){frm.add_custom_button(__("Load Eligible Items"),()=>act(frm,"load_eligible_items",__("Eligible items loaded")),__("Prepare"));frm.add_custom_button(__("Load Eligible Stores"),()=>stores(frm),__("Prepare"))}if(frm.doc.styles?.length&&frm.doc.stores?.length&&frm.doc.status!=="Counts Generated")frm.add_custom_button(__("Generate Store Counts"),()=>frappe.confirm(__("Generate one Store Cycle Count for each selected store?"),()=>act(frm,"generate_store_counts",__("Store counts generated"))),__("Execute"))},item_year:rf,season:rf,collection:rf,drop:rf,main_group:rf});
async function act(frm,m,msg,args={}){frappe.dom.freeze(__("Processing..."));try{let r=await frm.call(m,args);await frm.reload_doc();frappe.show_alert({message:msg,indicator:"green"});return r}finally{frappe.dom.unfreeze()}}
async function stores(frm){let r=await act(frm,"load_eligible_stores",__("Eligible stores loaded")),d=r.message||{},a=d.ambiguous||[],m=d.missing||[];if(m.length)frappe.msgprint({title:__("Stores Without Allowed User"),indicator:"orange",message:__("No Warehouse Users Allowed were found for:<br>{0}",[m.map(x=>frappe.utils.escape_html(x)).join("<br>")])});if(a.length)dlg(frm,a)}
function dlg(frm,s){let rows=s.map((r,i)=>`<tr><td>${frappe.utils.escape_html(r.warehouse)}</td><td><select class="form-control cu" data-i="${i}"><option value="">${__("Select User")}</option>${r.users.map(u=>`<option value="${frappe.utils.escape_html(u)}">${frappe.utils.escape_html(u)}</option>`).join("")}</select></td></tr>`).join("");let d=new frappe.ui.Dialog({title:__("Assign Cycle Count Store Users"),size:"large",fields:[{fieldname:"h",fieldtype:"HTML",options:`<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("Store")}</th><th>${__("Assigned User")}</th></tr></thead><tbody>${rows}</tbody></table></div>`}],primary_action_label:__("Confirm Assignments"),async primary_action(){let a={},bad=false;d.$wrapper.find(".cu").each(function(){let i=cint($(this).data("i")),u=$(this).val();if(!u)bad=true;a[s[i].warehouse]=u});if(bad){frappe.msgprint(__("Select a user for every listed store."));return}d.hide();await act(frm,"assign_store_users",__("Store users assigned"),{assignments:JSON.stringify(a)})}});d.show()}
function rf(frm){let id=(frm._ccfr||0)+1;frm._ccfr=id;return frappe.call({method:M,args:Object.fromEntries(F.map(x=>[x,frm.doc[x]]))}).then(r=>{if(id!==frm._ccfr)return;let d=r.message||{},o=d.options||{};for(let f of F)frm.set_df_property(f,"options",["",...(o[f]||[])].join("\n"));frm.refresh_fields(F);if((d.configuration_errors||[]).length)frappe.msgprint({title:__("Cycle Count Filter Configuration"),indicator:"orange",message:d.configuration_errors.join("<br>")})})}

frappe.ui.form.on("Cycle Count Plan Store", {
  form_render(frm) {
    configure_store_user_query(frm);
  },
  warehouse(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (row.assigned_to) {
      frappe.model.set_value(cdt, cdn, "assigned_to", "");
    }
    configure_store_user_query(frm);
  }
});

function configure_store_user_query(frm) {
  if (!frm.fields_dict.stores) return;

  frm.set_query("assigned_to", "stores", (doc, cdt, cdn) => {
    const row = locals[cdt][cdn];
    return {
      query: ALLOWED_STORE_USER_QUERY,
      filters: {
        warehouse: row.warehouse || ""
      }
    };
  });
}
