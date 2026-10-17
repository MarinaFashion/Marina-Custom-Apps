from __future__ import annotations

import frappe


def execute():
    if not frappe.db.exists("DocType", "POS Reconciliation Record"):
        return

    # Matching Not Settled already expresses the business condition, so the
    # duplicate One Side Matching resolution is retired.
    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record`
        SET resolution_status = 'Pending'
        WHERE resolution_status = 'One Side Matching'
        """
    )

    # Split the former generic Bank Only state using the statement evidence
    # already projected onto each reconciliation record.
    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record`
        SET match_status = CASE
            WHEN bank_statement_status = 'Fully Reconciled'
                THEN 'Bank Only - Settled'
            ELSE 'Bank Only - Not Settled'
        END
        WHERE match_status = 'Bank Only'
        """
    )
