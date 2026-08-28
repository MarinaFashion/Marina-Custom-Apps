from frappe import _

def get_data(data):
    data = dict(data or {})
    internal_links = dict(data.get("internal_links") or {})
    internal_links["Stock Transfer Audit Record"] = "custom_stock_transfer_audit_record"
    data["internal_links"] = internal_links
    transactions = list(data.get("transactions") or [])
    if not any("Stock Transfer Audit Record" in (g.get("items") or []) for g in transactions):
        transactions.append({"label": _("Audit"), "items": ["Stock Transfer Audit Record"]})
    data["transactions"] = transactions
    return data
