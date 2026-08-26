import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from marina_custom_apps.stock_transfer_audit.audit_service import get_transfer_snapshot, get_unaudited_received_transfers

class StockTransferAuditRun(Document):
    def validate(self):
        self._validate_dates(); self._update_counts()
    def before_submit(self):
        self._validate_dates()
        if not self.transfers: frappe.throw(_("Load at least one transfer before submitting the Audit Run."))
        for row in self.transfers:
            if frappe.db.exists("Stock Transfer Audit Record",{"original_send_stock":row.original_send_stock}):
                frappe.throw(_("Send Stock {0} is already in the Audit Register. Reload Transfers.").format(row.original_send_stock))
            get_transfer_snapshot(row.original_send_stock,row.receive_stock)
    def on_submit(self):
        for row in self.transfers:
            snap=get_transfer_snapshot(row.original_send_stock,row.receive_stock)
            rec=frappe.new_doc("Stock Transfer Audit Record")
            rec.record_type="Audit Run"; rec.audit_run=self.name; rec.original_send_stock=snap["original_send_stock"]; rec.receive_stock=snap["receive_stock"]
            rec.audit_status="Clean" if snap["audit_result"]=="Clean" else "Open"; rec.resolution_method="Auto Clean" if snap["audit_result"]=="Clean" else ""
            rec.resolution_notes="No discrepancy found during audit." if snap["audit_result"]=="Clean" else ""; rec.insert(ignore_permissions=True)
            frappe.db.set_value("Stock Transfer Audit Run Transfer",row.name,"audit_record",rec.name,update_modified=False)
        frappe.db.set_value(self.doctype,self.name,"run_status","Completed",update_modified=False)
    @frappe.whitelist()
    def load_transfers(self):
        if self.docstatus != 0: frappe.throw(_("Transfers can only be loaded into a Draft Audit Run."))
        self._validate_dates(); snaps=get_unaudited_received_transfers(self.from_date,self.to_date); self.set("transfers",[])
        for s in snaps:
            self.append("transfers",{"posting_date":s["posting_date"],"receive_stock":s["receive_stock"],"original_send_stock":s["original_send_stock"],"source_warehouse":s["source_warehouse"],"target_warehouse":s["target_warehouse"],"total_sent_qty":s["total_sent_qty"],"total_received_qty":s["total_received_qty"],"total_variance_qty":s["total_variance_qty"],"total_abs_variance_qty":s["total_abs_variance_qty"],"audit_result":s["audit_result"]})
        self._update_counts(); return {"loaded_count":len(self.transfers),"clean_count":self.clean_count,"variance_count":self.variance_count}
    def _validate_dates(self):
        if not self.from_date or not self.to_date: frappe.throw(_("From Date and To Date are required."))
        if self.from_date > self.to_date: frappe.throw(_("From Date cannot be after To Date."))
    def _update_counts(self):
        rows=self.transfers or []; self.total_transfers=len(rows); self.clean_count=sum(1 for r in rows if r.audit_result=="Clean"); self.variance_count=sum(1 for r in rows if r.audit_result=="Variance")
        self.total_variance_qty=sum(flt(r.total_variance_qty) for r in rows); self.total_abs_variance_qty=sum(flt(r.total_abs_variance_qty) for r in rows)
