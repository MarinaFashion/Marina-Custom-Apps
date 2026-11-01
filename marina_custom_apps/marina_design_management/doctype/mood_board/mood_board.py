import frappe
from frappe.model.document import Document


class MoodBoard(Document):
    def validate(self):
        from marina_custom_apps.design_management.clean_milestones.team import validate_board
        validate_board(self)
        self.mood_board_name = (self.mood_board_name or "").strip()
        if not self.mood_board_name:
            frappe.throw("Mood Board Name is required")

    def on_update(self):
        old = self.get_doc_before_save()
        if not old or not frappe.db.exists("DocType","Design Code"):
            return
        changed = {k:self.get(k) for k in ("year","season","collection","drop","display_date") if self.get(k) != old.get(k)}
        if changed:
            # paginated to avoid reading all designs into RAM.
            for offset in range(0,1000000,200):
                names = frappe.get_all("Design Code",filters={"mood_board":self.name},pluck="name",
                                      limit_start=offset,limit_page_length=200,order_by="name asc")
                for name in names:
                    frappe.db.set_value("Design Code",name,changed,update_modified=False)
                if len(names)<200:break

    def on_trash(self):
        if frappe.db.exists("Design Code",{"mood_board":self.name}):
            frappe.throw("Cannot delete a Mood Board with linked Design Codes")
