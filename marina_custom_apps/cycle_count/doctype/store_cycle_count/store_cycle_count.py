import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime
from marina_custom_apps.cycle_count.utils import ensure_counter, is_stock_manager, require_stock_manager, bin_snapshot

class StoreCycleCount(Document):
    def validate(self):
        self._protect_scope()
        self._summary()

    def before_submit(self):
        require_stock_manager()
        if self.status != "Submitted for Review":
            frappe.throw(_("Count must be Submitted for Review before approval."))
        self._summary()
        if self.counted_lines != self.total_lines:
            frappe.throw(_("All assigned lines must be counted."))

    def on_submit(self):
        require_stock_manager()
        sr=self._make_reconciliation()
        if sr:
            self.db_set("stock_reconciliation", sr.name, update_modified=False)
            self.db_set("status","Reconciliation Created",update_modified=False)
        else:
            self.db_set("status","Reconciled",update_modified=False)

    def before_cancel(self):
        require_stock_manager()
        if self.stock_reconciliation and frappe.db.exists("Stock Reconciliation", self.stock_reconciliation):
            sr=frappe.get_doc("Stock Reconciliation", self.stock_reconciliation)
            if sr.docstatus == 1:
                frappe.throw(_("Cancel linked Stock Reconciliation {0} first.").format(sr.name))
            if sr.docstatus == 0:
                frappe.delete_doc("Stock Reconciliation", sr.name, ignore_permissions=True, force=True)

    def on_cancel(self):
        self.db_set("status","Cancelled",update_modified=False)

    @frappe.whitelist()
    def start_count(self):
        ensure_counter(self)
        if self.docstatus != 0 or self.status not in ("Assigned","Recount Requested"):
            frappe.throw(_("This count cannot be started now."))
        snap=bin_snapshot(self.warehouse, [r.item_code for r in self.items])
        for r in self.items:
            v=snap.get(r.item_code,{})
            r.system_qty=flt(v.get("qty")); r.valuation_rate=flt(v.get("rate"))
            r.variance_qty=0; r.variance_percent=0; r.variance_value=0
        self.count_started_on=now_datetime(); self.count_completed_on=None; self.status="Counting"
        self.flags.allow_cycle_count_action = True
        self.save(ignore_permissions=True)

    @frappe.whitelist()
    def submit_count(self):
        ensure_counter(self)
        if self.docstatus != 0 or self.status != "Counting":
            frappe.throw(_("Only an active count can be submitted."))
        missing=[r.item_code for r in self.items if not r.counted]
        if missing:
            frappe.throw(_("Every line must be counted, including zero quantities. Missing examples: {0}").format(", ".join(missing[:10])))
        self.count_completed_on=now_datetime(); self.status="Submitted for Review"; self._summary()
        self.flags.allow_cycle_count_action = True
        self.save(ignore_permissions=True)

    @frappe.whitelist()
    def request_recount(self):
        require_stock_manager()
        if self.docstatus != 0 or self.status != "Submitted for Review":
            frappe.throw(_("Recount can only be requested after store submission."))
        for r in self.items:
            r.first_count_qty=r.counted_qty; r.first_variance_qty=r.variance_qty; r.counted=0; r.counted_qty=0; r.variance_qty=0; r.variance_percent=0; r.variance_value=0
        self.count_started_on=None; self.count_completed_on=None; self.status="Recount Requested"; self._summary()
        self.flags.allow_cycle_count_action = True
        self.save(ignore_permissions=True)

    @frappe.whitelist()
    def scan_barcode(self, barcode):
        ensure_counter(self)
        if self.docstatus != 0 or self.status != "Counting":
            frappe.throw(_("Start the count before scanning."))
        barcode=(barcode or "").strip()
        for r in self.items:
            if barcode in (r.barcode, r.item_code):
                r.counted_qty=flt(r.counted_qty)+1; r.counted=1; self._row(r); self._summary()
                self.flags.allow_cycle_count_action = True
                self.save(ignore_permissions=True)
                return {"item_code":r.item_code,"size":r.size,"counted_qty":r.counted_qty}
        frappe.throw(_("Barcode {0} is outside the assigned cycle-count scope.").format(barcode))

    def _protect_scope(self):
        """Prevent store counters from changing assignment, scope, or blind/system fields."""
        if self.is_new() or is_stock_manager():
            return

        old = self.get_doc_before_save()
        if not old:
            return

        immutable_parent = (
            "cycle_count_plan",
            "company",
            "warehouse",
            "assigned_to",
            "count_date",
            "count_window",
        )
        for fieldname in immutable_parent:
            if self.get(fieldname) != old.get(fieldname):
                frappe.throw(
                    _("{0} cannot be changed by the store counter.").format(
                        self.meta.get_label(fieldname)
                    )
                )

        # Start Count / Barcode / Submit Count are trusted server actions.
        if getattr(self.flags, "allow_cycle_count_action", False):
            return

        if self.status != old.status:
            frappe.throw(_("Cycle Count status can only be changed using the provided actions."))

        old_rows = {row.name: row for row in old.items}
        new_rows = {row.name: row for row in self.items if row.name}

        if set(old_rows) != set(new_rows):
            frappe.throw(
                _("Assigned Cycle Count items cannot be added, removed, or replaced manually.")
            )

        protected_fields = (
            "item_code",
            "item_name",
            "item_template",
            "size",
            "barcode",
            "system_qty",
            "variance_qty",
            "variance_percent",
            "valuation_rate",
            "variance_value",
            "first_count_qty",
            "first_variance_qty",
            "unexpected_item",
        )

        for name, row in new_rows.items():
            old_row = old_rows[name]

            for fieldname in protected_fields:
                if row.get(fieldname) != old_row.get(fieldname):
                    frappe.throw(
                        _("System-controlled Cycle Count fields cannot be changed manually.")
                    )

            if old.status != "Counting":
                if row.counted != old_row.counted or flt(row.counted_qty) != flt(old_row.counted_qty):
                    frappe.throw(
                        _("Physical quantities can only be entered while the count is in Counting status.")
                    )
    @frappe.whitelist()
    def add_unexpected_barcode(self, barcode):
        """Add an out-of-scope scanned item as a clearly flagged audit line."""
        ensure_counter(self)
        if self.docstatus != 0 or self.status != "Counting":
            frappe.throw(_("Start the count before adding an unexpected item."))

        barcode = (barcode or "").strip()
        if not barcode:
            frappe.throw(_("Barcode is required."))

        item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
        if not item_code and frappe.db.exists("Item", barcode):
            item_code = barcode

        if not item_code:
            frappe.throw(_("No Item was found for barcode {0}.").format(barcode))

        for r in self.items:
            if r.item_code == item_code:
                r.counted_qty = flt(r.counted_qty) + 1
                r.counted = 1
                self._row(r)
                self._summary()
                self.flags.allow_cycle_count_action = True
                self.save(ignore_permissions=True)
                return {
                    "item_code": r.item_code,
                    "size": r.size,
                    "counted_qty": r.counted_qty,
                    "unexpected_item": r.unexpected_item,
                }

        item = frappe.db.get_value(
            "Item",
            item_code,
            ["item_name", "variant_of"],
            as_dict=True,
        )
        snap = bin_snapshot(self.warehouse, [item_code]).get(item_code, {})

        size_value = frappe.db.get_value(
            "Item Variant Attribute",
            {"parent": item_code, "attribute": ["in", ["Size", "SIZE", "size"]]},
            "attribute_value",
        )
        primary_barcode = frappe.db.get_value(
            "Item Barcode",
            {"parent": item_code},
            "barcode",
        )

        r = self.append(
            "items",
            {
                "item_code": item_code,
                "item_name": item.item_name,
                "item_template": item.variant_of or item_code,
                "size": size_value,
                "barcode": primary_barcode or barcode,
                "system_qty": flt(snap.get("qty")),
                "valuation_rate": flt(snap.get("rate")),
                "counted": 1,
                "counted_qty": 1,
                "unexpected_item": 1,
            },
        )
        self._row(r)
        self._summary()
        self.flags.allow_cycle_count_action = True
        self.save(ignore_permissions=True)

        return {
            "item_code": r.item_code,
            "size": r.size,
            "counted_qty": r.counted_qty,
            "unexpected_item": 1,
        }
    def _row(self,r):
        if not r.counted:
            r.variance_qty=0; r.variance_percent=0; r.variance_value=0; return
        r.variance_qty=flt(r.counted_qty)-flt(r.system_qty)
        r.variance_percent=(r.variance_qty/abs(flt(r.system_qty))*100) if flt(r.system_qty) else (100 if r.variance_qty else 0)
        r.variance_value=r.variance_qty*flt(r.valuation_rate)

    def _summary(self):
        for r in self.items: self._row(r)
        self.total_lines=len(self.items)
        self.counted_lines=sum(1 for r in self.items if r.counted)
        self.variance_lines=sum(1 for r in self.items if r.counted and abs(flt(r.variance_qty))>1e-9)
        self.total_abs_variance_qty=sum(abs(flt(r.variance_qty)) for r in self.items if r.counted)
        self.total_variance_value=sum(flt(r.variance_value) for r in self.items if r.counted)

    def _make_reconciliation(self):
        rows=[r for r in self.items if r.counted and abs(flt(r.variance_qty))>1e-9]
        if not rows: return None
        current=bin_snapshot(self.warehouse,[r.item_code for r in rows])
        sr=frappe.new_doc("Stock Reconciliation"); sr.company=self.company
        if sr.meta.has_field("purpose"): sr.purpose="Stock Reconciliation"
        if sr.meta.has_field("custom_store_cycle_count"): sr.custom_store_cycle_count=self.name
        for r in rows:
            cur=current.get(r.item_code,{})
            # Apply the discovered variance to CURRENT stock, so legitimate later
            # transactions are preserved even if approval happens after opening.
            qty=flt(cur.get("qty"))+flt(r.variance_qty)
            rate=flt(cur.get("rate")) or flt(r.valuation_rate)
            sr.append("items",{"item_code":r.item_code,"warehouse":self.warehouse,"qty":qty,"valuation_rate":rate})
        sr.insert(ignore_permissions=True)
        return sr
