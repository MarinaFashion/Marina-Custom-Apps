import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from marina_custom_apps.stock_transfer_audit.audit_service import get_transfer_snapshot
from marina_custom_apps.stock_transfer_audit.status_service import (
    ACTION_IGNORE,
    ACTION_MOVE_TO_SOURCE,
    ACTION_MOVE_TO_TARGET,
    get_record_processing_status,
    update_record_status,
    update_run_status,
)

VALID_ACTIONS = {ACTION_MOVE_TO_SOURCE, ACTION_MOVE_TO_TARGET, ACTION_IGNORE}
TRANSFER_BETWEEN = "Transfer Between"


def _line_key(row):
    return (
        cint(row.get("unexpected_item")),
        row.get("send_stock_detail") or "",
        row.get("receive_stock_detail") or "",
        row.get("item_code") or "",
    )


def _decision_map(rows):
    result = {}
    for row in rows or []:
        result[_line_key(row)] = (
            row.get("action"),
            row.get("ignore_reason"),
            (row.get("ignore_notes") or "").strip(),
        )
    return result


class StockTransferAuditRecord(Document):
    def validate(self):
        if not self.original_send_stock:
            frappe.throw(_("Original Send Stock is required."))

        duplicate = frappe.db.exists(
            "Stock Transfer Audit Record",
            {
                "original_send_stock": self.original_send_stock,
                "name": ["!=", self.name or ""],
            },
        )
        if duplicate:
            frappe.throw(
                _("Send Stock {0} is already registered in Audit Record {1}.").format(
                    self.original_send_stock, duplicate
                )
            )

        if not self.record_type:
            self.record_type = (
                "Audit Run" if self.audit_run else "Legacy / Previous Process"
            )

        # Once submitted, the audited snapshot must remain immutable.
        # Only the decision fields marked allow_on_submit may change.
        if self.docstatus == 1 and not self.is_new():
            self._protect_actions_when_corrections_exist()
            self._apply_ignore_metadata()
            self._validate_exception_actions()
            self.processing_status = get_record_processing_status(self)
            return

        decisions = {}
        for row in self.items or []:
            decisions[_line_key(row)] = {
                "action": row.get("action"),
                "ignore_reason": row.get("ignore_reason"),
                "ignore_notes": row.get("ignore_notes"),
                "ignored_by": row.get("ignored_by"),
                "ignored_on": row.get("ignored_on"),
            }

        snap = get_transfer_snapshot(
            self.original_send_stock, self.receive_stock or None
        )

        for fieldname in (
            "receive_stock",
            "source_warehouse",
            "transit_warehouse",
            "target_warehouse",
            "total_sent_qty",
            "total_received_qty",
            "total_variance_qty",
            "total_abs_variance_qty",
            "audit_result",
        ):
            self.set(fieldname, snap[fieldname])

        self.set("items", [])

        for item in snap["items"]:
            variance = flt(item.get("discrepancy_qty"))
            if abs(variance) < 0.000001:
                continue

            previous = decisions.get(_line_key(item), {})
            action = previous.get("action") or (
                ACTION_MOVE_TO_SOURCE if variance > 0 else ACTION_MOVE_TO_TARGET
            )

            if action not in VALID_ACTIONS:
                frappe.throw(
                    _("Invalid Action {0} for item {1}.").format(
                        action, item.get("item_code")
                    )
                )

            row = dict(item)
            row.update(
                {
                    "source_warehouse": snap["source_warehouse"],
                    "target_warehouse": snap["target_warehouse"],
                    "action": action,
                    "ignore_reason": previous.get("ignore_reason"),
                    "ignore_notes": previous.get("ignore_notes"),
                    "ignored_by": previous.get("ignored_by"),
                    "ignored_on": previous.get("ignored_on"),
                }
            )

            if action == ACTION_IGNORE:
                row["ignored_by"] = row.get("ignored_by") or frappe.session.user
                row["ignored_on"] = row.get("ignored_on") or now_datetime()
            else:
                row["ignore_reason"] = None
                row["ignore_notes"] = None
                row["ignored_by"] = None
                row["ignored_on"] = None

            self.append("items", row)

        if self.record_type == "Legacy / Previous Process":
            self.audit_status = "Legacy Closed"
            self.resolution_method = (
                self.resolution_method or "Legacy / Previous Process"
            )
        elif not self.audit_status:
            self.audit_status = (
                "Clean" if snap["audit_result"] == "Clean" else "Open"
            )

        if self.audit_status == "Clean" and not self.resolution_method:
            self.resolution_method = "Auto Clean"

        self._validate_exception_actions()
        self.processing_status = (
            get_record_processing_status(self)
            if not self.is_new()
            else ("Completed" if self.audit_result == "Clean" else "Pending")
        )

    def before_insert(self):
        if not self.audited_by:
            self.audited_by = frappe.session.user

    def before_cancel(self):
        active = frappe.get_all(
            "Stock Entry",
            filters={
                "custom_stock_transfer_audit_record": self.name,
                "docstatus": ["<", 2],
            },
            fields=["name", "docstatus"],
            limit_page_length=20,
        )
        if active:
            draft = [r.name for r in active if cint(r.docstatus) == 0]
            submitted = [r.name for r in active if cint(r.docstatus) == 1]
            parts = []
            if submitted:
                parts.append(
                    _("cancel submitted Transfer Between: {0}").format(
                        ", ".join(submitted)
                    )
                )
            if draft:
                parts.append(
                    _("delete draft Transfer Between: {0}").format(
                        ", ".join(draft)
                    )
                )
            frappe.throw(
                _("Before cancelling this Audit Record, {0}.").format(
                    " and ".join(parts)
                )
            )

    def on_cancel(self):
        self.db_set("processing_status", "Cancelled", update_modified=False)
        if self.audit_run:
            update_run_status(self.audit_run)

    def on_trash(self):
        linked = frappe.get_all(
            "Stock Entry",
            filters={"custom_stock_transfer_audit_record": self.name},
            pluck="name",
            limit_page_length=20,
        )
        if linked:
            frappe.throw(
                _(
                    "Delete the related Transfer Between Stock Entry/Entries first: {0}"
                ).format(", ".join(linked))
            )

    def on_update(self):
        if not self.is_new():
            update_record_status(self.name)

    def _active_corrections(self):
        return frappe.get_all(
            "Stock Entry",
            filters={
                "custom_stock_transfer_audit_record": self.name,
                "docstatus": ["<", 2],
            },
            fields=["name", "docstatus"],
            limit_page_length=20,
        )

    def _protect_actions_when_corrections_exist(self):
        before = self.get_doc_before_save()
        if not before:
            return

        if _decision_map(before.items) == _decision_map(self.items):
            return

        active = self._active_corrections()
        if not active:
            return

        draft = [r.name for r in active if cint(r.docstatus) == 0]
        submitted = [r.name for r in active if cint(r.docstatus) == 1]
        instructions = []

        if submitted:
            instructions.append(
                _("cancel submitted correction(s): {0}").format(
                    ", ".join(submitted)
                )
            )
        if draft:
            instructions.append(
                _("delete draft correction(s): {0}").format(", ".join(draft))
            )

        frappe.throw(
            _(
                "Action / Ignore decisions cannot be changed while active correction "
                "Stock Entries exist. First {0}."
            ).format(" and ".join(instructions))
        )

    def _apply_ignore_metadata(self):
        before = self.get_doc_before_save()
        previous = {
            _line_key(row): row
            for row in ((before.items if before else []) or [])
        }

        for row in self.items or []:
            old = previous.get(_line_key(row))

            if row.action == ACTION_IGNORE:
                if old and old.action == ACTION_IGNORE:
                    row.ignored_by = old.ignored_by
                    row.ignored_on = old.ignored_on
                else:
                    row.ignored_by = frappe.session.user
                    row.ignored_on = now_datetime()
            else:
                row.ignore_reason = None
                row.ignore_notes = None
                row.ignored_by = None
                row.ignored_on = None

    def _validate_exception_actions(self):
        for index, row in enumerate(self.items or [], start=1):
            if abs(flt(row.discrepancy_qty)) < 0.000001:
                frappe.throw(
                    _("Row {0}: zero-variance rows are not allowed.").format(index)
                )

            if row.action not in VALID_ACTIONS:
                frappe.throw(
                    _(
                        "Row {0}: Action must be Move to Source, Move to Target, or Ignore."
                    ).format(index)
                )

            if (
                row.source_warehouse != self.source_warehouse
                or row.target_warehouse != self.target_warehouse
            ):
                frappe.throw(
                    _("Row {0}: warehouses are system controlled.").format(index)
                )

            if row.action == ACTION_IGNORE:
                if not row.ignore_reason:
                    frappe.throw(
                        _("Row {0}: Ignore Reason is required.").format(index)
                    )
                if row.ignore_reason == "Other" and not (
                    row.ignore_notes or ""
                ).strip():
                    frappe.throw(
                        _(
                            "Row {0}: Ignore Notes are required when reason is Other."
                        ).format(index)
                    )

    def _correction_groups(self):
        groups = {"to_source": {}, "to_target": {}}

        for row in self.items or []:
            variance = flt(row.discrepancy_qty)
            qty = abs(variance)

            if qty < 0.000001 or row.action == ACTION_IGNORE:
                continue

            group = None
            if variance > 0 and row.action == ACTION_MOVE_TO_SOURCE:
                group = "to_source"
            elif variance < 0 and row.action == ACTION_MOVE_TO_TARGET:
                group = "to_target"

            if group:
                groups[group][row.item_code] = (
                    flt(groups[group].get(row.item_code)) + qty
                )

        return groups

    def _validate_item_for_auto_correction(self, item_code):
        item = frappe.db.get_value(
            "Item",
            item_code,
            ["stock_uom", "has_batch_no", "has_serial_no"],
            as_dict=True,
        )

        if not item:
            frappe.throw(_("Item {0} does not exist.").format(item_code))

        if item.has_batch_no or item.has_serial_no:
            frappe.throw(
                _(
                    "Item {0} uses Batch or Serial tracking. "
                    "Create its audit correction manually."
                ).format(item_code)
            )

        return item.stock_uom

    def _existing_correction(self, direction):
        return frappe.db.exists(
            "Stock Entry",
            {
                "custom_stock_transfer_audit_record": self.name,
                "custom_audit_correction_direction": direction,
                "stock_entry_type": TRANSFER_BETWEEN,
                "docstatus": ["<", 2],
            },
        )

    def _create_transfer_between(self, group, item_qty):
        if group == "to_source":
            from_warehouse = self.target_warehouse
            to_warehouse = self.source_warehouse
            direction = ACTION_MOVE_TO_SOURCE
        else:
            from_warehouse = self.source_warehouse
            to_warehouse = self.target_warehouse
            direction = ACTION_MOVE_TO_TARGET

        original = frappe.get_doc("Stock Entry", self.original_send_stock)

        correction = frappe.new_doc("Stock Entry")
        correction.stock_entry_type = TRANSFER_BETWEEN
        correction.purpose = "Material Transfer"
        correction.company = original.company
        correction.from_warehouse = from_warehouse
        correction.to_warehouse = to_warehouse
        correction.custom_stock_transfer_audit_record = self.name
        correction.custom_audit_correction_direction = direction
        correction.remarks = _(
            "Stock Transfer Audit correction from {0}: {1}"
        ).format(self.name, direction)

        for item_code, qty in sorted(item_qty.items()):
            uom = self._validate_item_for_auto_correction(item_code)
            correction.append(
                "items",
                {
                    "item_code": item_code,
                    "qty": qty,
                    "transfer_qty": qty,
                    "uom": uom,
                    "stock_uom": uom,
                    "conversion_factor": 1,
                    "s_warehouse": from_warehouse,
                    "t_warehouse": to_warehouse,
                },
            )

        correction.insert()
        return correction.name

    @frappe.whitelist()
    def generate_correction_stock_entries(self):
        self.check_permission("write")
        self.reload()

        if self.docstatus != 1:
            frappe.throw(
                _("Audit Record must be submitted before generating corrections.")
            )

        if self.record_type != "Audit Run" or self.audit_result != "Variance":
            frappe.throw(
                _(
                    "Only submitted Audit Run records with Variance can generate corrections."
                )
            )

        self._validate_exception_actions()
        groups = self._correction_groups()
        created = []
        existing = []

        for group, direction in (
            ("to_source", ACTION_MOVE_TO_SOURCE),
            ("to_target", ACTION_MOVE_TO_TARGET),
        ):
            if not groups[group]:
                continue

            linked = self._existing_correction(direction)
            if linked:
                existing.append(linked)
            else:
                created.append(
                    self._create_transfer_between(group, groups[group])
                )

        if self.resolution_method != "Audit Correction":
            self.db_set(
                "resolution_method",
                "Audit Correction",
                update_modified=False,
            )

        update_record_status(self.name)

        return {
            "created": created,
            "existing": existing,
            "message": (
                _("Created draft correction Stock Entry(s): {0}").format(
                    ", ".join(created)
                )
                if created
                else _(
                    "No Transfer Between is required. "
                    "Ignored/accepted lines are considered solved."
                )
            ),
        }
