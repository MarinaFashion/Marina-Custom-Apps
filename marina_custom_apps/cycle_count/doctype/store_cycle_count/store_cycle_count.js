function cc_scope_controls(frm){
  const g=frm.fields_dict.items?.grid;
  if(!g)return;
  const can_manage=cc_manager();
  g.cannot_add_rows=!can_manage;
  g.cannot_delete_rows=!can_manage;
  g.wrapper.find(".grid-add-row, .grid-remove-rows, .grid-delete-row").toggle(can_manage);
}
function cc_manager(){return frappe.session.user==="Administrator" || frappe.user.has_role("Stock Manager");}
function cc_blind(frm){
  const g=frm.fields_dict.items?.grid;if(!g)return;
  ["system_qty","variance_qty","variance_percent","valuation_rate","variance_value","first_count_qty","first_variance_qty"].forEach(f=>{
    const df=g.docfields.find(x=>x.fieldname===f); if(df) df.hidden=cc_manager()?0:1;
  }); g.refresh();
}
frappe.ui.form.on("Store Cycle Count",{
  refresh(frm){
    cc_scope_controls(frm);
    cc_blind(frm);
    const mine=frm.doc.assigned_to===frappe.session.user || cc_manager();
    if(frm.doc.docstatus===0 && mine && ["Assigned","Recount Requested"].includes(frm.doc.status))
      frm.add_custom_button(__("Start Count"),()=>frappe.confirm(__("Confirm the store is closed for transactions and start the stock snapshot now?"),()=>frm.call("start_count").then(()=>frm.reload_doc())),__("Count"));
    if(frm.doc.docstatus===0 && mine && frm.doc.status==="Counting")
      frm.add_custom_button(__("Submit Count for Review"),()=>frm.call("submit_count").then(()=>frm.reload_doc()),__("Count"));
    if(frm.doc.docstatus===0 && cc_manager() && frm.doc.status==="Submitted for Review")
      frm.add_custom_button(__("Request Recount"),()=>frm.call("request_recount").then(()=>frm.reload_doc()),__("Review"));
    if(frm.doc.stock_reconciliation)
      frm.add_custom_button(__("Open Stock Reconciliation"),()=>frappe.set_route("Form","Stock Reconciliation",frm.doc.stock_reconciliation));
  },
  barcode_scan(frm){
    if(!frm.doc.barcode_scan || frm.doc.entry_mode!=="Barcode") return;
    const b=frm.doc.barcode_scan.trim(); frm.set_value("barcode_scan","");
    frm.call("scan_barcode",{barcode:b})
      .then(r=>{
        if(r.message) frappe.show_alert({
          message:__("{0} {1} - Counted: {2}",[r.message.item_code,r.message.size||"",r.message.counted_qty]),
          indicator:"green"
        });
        frm.reload_doc();
      })
      .catch(()=>{
        frappe.confirm(
          __("Barcode {0} is outside the assigned count. Add it as an Unexpected Item?",[b]),
          ()=>frm.call("add_unexpected_barcode",{barcode:b}).then(r=>{
            if(r.message) frappe.show_alert({
              message:__("Unexpected item {0} added - Counted: {1}",[r.message.item_code,r.message.counted_qty]),
              indicator:"orange"
            });
            frm.reload_doc();
          })
        );
      });
  }
});
frappe.ui.form.on("Store Cycle Count Item",{
  counted_qty(frm,cdt,cdn){if(frm.doc.status==="Counting") frappe.model.set_value(cdt,cdn,"counted",1);}
});
