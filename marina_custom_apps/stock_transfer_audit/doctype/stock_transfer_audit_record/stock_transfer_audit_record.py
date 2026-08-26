import frappe
from frappe import _
from frappe.model.document import Document
from marina_custom_apps.stock_transfer_audit.audit_service import get_transfer_snapshot

class StockTransferAuditRecord(Document):
    def validate(self):
        if not self.original_send_stock: frappe.throw(_("Original Send Stock is required."))
        duplicate=frappe.db.exists("Stock Transfer Audit Record",{"original_send_stock":self.original_send_stock,"name":["!=",self.name or ""]})
        if duplicate: frappe.throw(_("Send Stock {0} is already registered in Audit Record {1}.").format(self.original_send_stock,duplicate))
        if not self.record_type: self.record_type="Audit Run" if self.audit_run else "Legacy / Previous Process"
        snap=get_transfer_snapshot(self.original_send_stock,self.receive_stock or None)
        self.receive_stock=snap["receive_stock"]; self.source_warehouse=snap["source_warehouse"]; self.transit_warehouse=snap["transit_warehouse"]; self.target_warehouse=snap["target_warehouse"]
        self.total_sent_qty=snap["total_sent_qty"]; self.total_received_qty=snap["total_received_qty"]; self.total_variance_qty=snap["total_variance_qty"]; self.total_abs_variance_qty=snap["total_abs_variance_qty"]; self.audit_result=snap["audit_result"]
        self.set("items",[])
        for item in snap["items"]: self.append("items",item)
        if self.record_type=="Legacy / Previous Process":
            self.audit_status="Legacy Closed"; self.resolution_method=self.resolution_method or "Legacy / Previous Process"
        elif not self.audit_status: self.audit_status="Clean" if snap["audit_result"]=="Clean" else "Open"
        if self.audit_status=="Clean" and not self.resolution_method: self.resolution_method="Auto Clean"
    def before_insert(self):
        if not self.audited_by: self.audited_by=frappe.session.user
