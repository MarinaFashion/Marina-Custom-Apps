from frappe.utils import flt


def discrepancy_qty(sent_qty, actual_received_qty):
    """Positive = shortage, negative = excess."""
    return flt(sent_qty) - flt(actual_received_qty)


def safe_posting_qty(sent_qty, actual_received_qty):
    """Ledger quantity for an expected line under the agreed control model.

    Physical truth is stored separately in Actual Received Qty.
    The ledger does not automatically post more than was recorded as sent.
    """
    sent = max(flt(sent_qty), 0)
    actual = max(flt(actual_received_qty), 0)
    return min(sent, actual)


def reconciliation_values(sent_qty, actual_received_qty):
    sent = max(flt(sent_qty), 0)
    actual = max(flt(actual_received_qty), 0)
    return {
        "sent_qty": sent,
        "actual_received_qty": actual,
        "discrepancy_qty": discrepancy_qty(sent, actual),
        "posting_qty": safe_posting_qty(sent, actual),
    }
