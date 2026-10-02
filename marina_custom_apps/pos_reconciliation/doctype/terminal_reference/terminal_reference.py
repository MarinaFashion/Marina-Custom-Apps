from frappe.model.document import Document


def clean_text(value) -> str:
    return str(value or "").strip()


class TerminalReference(Document):
    def validate(self):
        self.terminal_id = clean_text(self.terminal_id)
        self.retailer_identifier = clean_text(self.retailer_identifier)
        self.branch_name = clean_text(self.branch_name)
        self.address = clean_text(self.address)
