import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from marina_custom_apps.stock_transfer_audit.audit_service import get_transfer_snapshot

ACTION_MOVE_TO_SOURCE = "Move to Source"
ACTION_MOVE_TO_TARGET = "Move to Target"
VALID_ACTIONS = {ACTION_MOVE_TO_SOURCE, ACTION_MOVE_TO_TARGET}
TRANSFER_BETWEEN = "Transfer Between"


def _line_key(row):
    return (
        cint(row.get("unexpected_item")),
        row.get("send_stock_detail") or "",
        row.get("receive_stock_detail") or "",
        row.get("item_code") or "",
    )


class StockTransferAuditRecord(Document):
    def validate(self):
        if not self.original_send_stock:
            frappe.throw(_("Original Send Stock is required."))

        duplicate = frappe.db.exists(
            "Stock Transfer Audit Record",
            {"original_send_stock": self.original_send_stock, "name": ["!=", self.name or ""]},
        )
        if duplicate:
            frappe.throw(_("Send Stock {0} is already registered in Audit Record {1}.").format(self.original_send_stock, duplicate))

        if not self.record_type:
            self.record_type = "Audit Run" if self.audit_run else "Legacy / Previous Process"

        selected_actions = {}
        for row in self.items or []:
            if row.get("action"):
                selected_actions[_line_key(row)] = row.action

        snap = get_transfer_snapshot(self.original_send_stock, self.receive_stock or None)
        self.receive_stock = snap["receive_stock"]
        self.source_warehouse = snap["source_warehouse"]
        self.transit_warehouse = snap["transit_warehouse"]
        self.target_warehouse = snap["target_warehouse"]
        self.total_sent_qty = snap["total_sent_qty"]
        self.total_received_qty = snap["total_received_qty"]
        self.total_variance_qty = snap["total_variance_qty"]
        self.total_abs_variance_qty = snap["total_abs_variance_qty"]
        self.audit_result = snap["audit_result"]

        self.set("items", [])
        for item in snap["items"]:
            variance = flt(item.get("discrepancy_qty"))
            if abs(variance) < 0.000001:
                continue
            action = selected_actions.get(_line_key(item))
            if not action:
                action = ACTION_MOVE_TO_SOURCE if variance > 0 else ACTION_MOVE_TO_TARGET
            if action not in VALID_ACTIONS:
                frappe.throw(_("Invalid Action {0} for item {1}.").format(action, item.get("item_code")))
            row = dict(item)
            row.update({"source_warehouse": snap["source_warehouse"], "target_warehouse": snap["target_warehouse"], "action": action})
            self.append("items", row)

        if self.record_type == "Legacy / Previous Process":
            self.audit_status = "Legacy Closed"
            self.resolution_method = self.resolution_method or "Legacy / Previous Process"
        elif not self.audit_status:
            self.audit_status = "Clean" if snap["audit_result"] == "Clean" else "Open"
        if self.audit_status == "Clean" and not self.resolution_method:
            self.resolution_method = "Auto Clean"

        self._validate_exception_actions()

    def before_insert(self):
        if not self.audited_by:
            self.audited_by = frappe.session.user

    def _validate_exception_actions(self):
        for index, row in enumerate(self.items or [], start=1):
            if abs(flt(row.discrepancy_qty)) < 0.000001:
                frappe.throw(_("Row {0}: zero-variance rows are not allowed in Audit Exceptions.").format(index))
            if row.action not in VALID_ACTIONS:
                frappe.throw(_("Row {0}: Action must be Move to Source or Move to Target.").format(index))
            if row.source_warehouse != self.source_warehouse:
                frappe.throw(_("Row {0}: Source Warehouse must remain {1}.").format(index, self.source_warehouse))
            if row.target_warehouse != self.target_warehouse:
                frappe.throw(_("Row {0}: Target Warehouse must remain {1}.").format(index, self.target_warehouse))

    def _correction_groups(self):
        groups = {"to_source": {}, "to_target": {}}
        for row in self.items or []:
            variance = flt(row.discrepancy_qty)
            qty = abs(variance)
            if qty < 0.000001:
                continue
            group = None
            # Receive Stock already credits the full SENT qty to Target.
            # Shortage + Move to Source therefore needs Target -> Source.
            if variance > 0 and row.action == ACTION_MOVE_TO_SOURCE:
                group = "to_source"
            # Excess/unexpected qty was not moved by Receive Stock and remains
            # represented at Source; Move to Target needs Source -> Target.
            elif variance < 0 and row.action == ACTION_MOVE_TO_TARGET:
                group = "to_target"
            if not group:
                continue
            groups[group][row.item_code] = flt(groups[group].get(row.item_code)) + qty
        return groups

    def _validate_item_for_auto_correction(self, item_code):
        item = frappe.db.get_value("Item", item_code, ["stock_uom", "has_batch_no", "has_serial_no"], as_dict=True)
        if not item:
            frappe.throw(_("Item {0} does not exist.").format(item_code))
        if item.has_batch_no or item.has_serial_no:
            frappe.throw(_("Item {0} uses Batch or Serial tracking. Create its audit correction manually so the exact Batch/Serial can be selected.").format(item_code))
        return item.stock_uom

    def _create_transfer_between(self, group, item_qty):
        if group == "to_source":
            from_warehouse = self.target_warehouse
            to_warehouse = self.source_warehouse
            direction_label = _("Move to Source")
        else:
            from_warehouse = self.source_warehouse
            to_warehouse = self.target_warehouse
            direction_label = _("Move to Target")

        original_send = frappe.get_doc("Stock Entry", self.original_send_stock)
        correction = frappe.new_doc("Stock Entry")
        correction.stock_entry_type = TRANSFER_BETWEEN
        correction.purpose = "Material Transfer"
        correction.company = original_send.company
        correction.from_warehouse = from_warehouse
        correction.to_warehouse = to_warehouse
        correction.remarks = _("Stock Transfer Audit correction from {0}: {1}").format(self.name, direction_label)

        for item_code, qty in sorted(item_qty.items()):
            stock_uom = self._validate_item_for_auto_correction(item_code)
            correction.append("items", {"item_code": item_code, "qty": qty, "transfer_qty": qty, "uom": stock_uom, "stock_uom": stock_uom, "conversion_factor": 1, "s_warehouse": from_warehouse, "t_warehouse": to_warehouse})

        correction.insert()
        return correction.name

    def _active_linked_stock_entry(self, fieldname):
        name = self.get(fieldname)
        if not name:
            return None
        status = frappe.db.get_value("Stock Entry", name, "docstatus")
        return name if status is not None and cint(status) < 2 else None

    @frappe.whitelist()
    def generate_correction_stock_entries(self):
        self.check_permission("write")
        self.reload()
        if self.record_type != "Audit Run":
            frappe.throw(_("Correction Stock Entries can be generated only for Audit Run records."))
        if self.audit_status != "Open" or self.audit_result != "Variance":
            frappe.throw(_("Only Open Audit Records with Variance can generate corrections."))

        # Compatibility for Audit Records created before v0.14.0:
        # validate() rebuilds the child table as exception-only and
        # assigns/preserves the selected Action values.
        self.save()
        self.reload()

        if not self.items:
            frappe.throw(_("This Audit Record has no exception lines."))

        self._validate_exception_actions()
        groups = self._correction_groups()
        created=[]; existing=[]
        mappings=[("to_source","correction_to_source_stock_entry",_("Move to Source")),("to_target","correction_to_target_stock_entry",_("Move to Target"))]
        for group, fieldname, label in mappings:
            item_qty=groups[group]
            if not item_qty:
                continue
            linked=self._active_linked_stock_entry(fieldname)
            if linked:
                existing.append(linked); continue
            name=self._create_transfer_between(group,item_qty)
            self.db_set(fieldname,name,update_modified=False)
            created.append(name)

        if created and self.resolution_method != "Audit Correction":
            self.db_set("resolution_method","Audit Correction",update_modified=False)

        return {"created":created,"existing":existing,"message":(_("Created draft correction Stock Entry(s): {0}").format(", ".join(created)) if created else _("No new correction Stock Entry is required for the selected Actions."))}
