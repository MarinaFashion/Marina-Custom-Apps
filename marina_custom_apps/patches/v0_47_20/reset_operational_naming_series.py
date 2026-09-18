from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate


def execute():
    """Reset every user-facing Marina naming series once during v0.47.20 migration."""
    year = getdate(nowdate()).year
    prefixes = (
        f"CCP-{year}-",
        f"SCC-{year}-",
        f"DCD-{year}-",
        f"SFR-{year}-",
        f"SAR-{year}-",
        f"TSB-{year}-",
        "SOP-",
        "SOP-V-",
        "STA-RUN-",
        "STA-REC-",
    )

    for prefix in prefixes:
        frappe.db.sql("delete from `tabSeries` where `name` = %s", (prefix,))
