from frappe.utils import flt


def discrepancy_qty(sent_qty, actual_received_qty):
    """Positive = shortage, negative = excess."""
    return flt(sent_qty) - flt(actual_received_qty)


def safe_posting_qty(sent_qty, actual_received_qty):
    """Ledger Qty equals Sent Qty so Transit closes completely.

    Actual Received Qty is physical evidence. Shortage/excess is settled later
    between physical warehouses by Stock Transfer Audit.
    """
    return max(flt(sent_qty), 0)

def reconciliation_values(sent_qty, actual_received_qty):
    sent = max(flt(sent_qty), 0)
    actual = max(flt(actual_received_qty), 0)
    return {
        "sent_qty": sent,
        "actual_received_qty": actual,
        "discrepancy_qty": discrepancy_qty(sent, actual),
        "posting_qty": safe_posting_qty(sent, actual),
    }
