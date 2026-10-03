from __future__ import annotations

import frappe


def execute():
    if not frappe.db.exists("DocType", "POS Reconciliation Record"):
        return

    # Preserve existing active manual clearances as Finance approvals.
    if frappe.db.exists("DocType", "POS Bank Manual Clearance"):
        frappe.db.sql(
            """
            UPDATE `tabPOS Bank Manual Clearance`
            SET
                finance_review_status = CASE
                    WHEN active = 1 THEN 'Checked & Approved'
                    ELSE COALESCE(NULLIF(finance_review_status, ''), 'Pending Review')
                END,
                finance_review_note = CASE
                    WHEN active = 1 AND (finance_review_note IS NULL OR finance_review_note = '') THEN reason
                    ELSE finance_review_note
                END,
                finance_reviewed_by = CASE
                    WHEN active = 1 AND (finance_reviewed_by IS NULL OR finance_reviewed_by = '') THEN cleared_by
                    ELSE finance_reviewed_by
                END,
                finance_reviewed_on = CASE
                    WHEN active = 1 AND finance_reviewed_on IS NULL THEN cleared_on
                    ELSE finance_reviewed_on
                END
            """
        )

    # Snapshot bank settlement / fee fields onto reconciliation records for
    # fast server-side filtering and selected-row totals without repeated joins.
    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record` r
        INNER JOIN `tabBank POS Transaction` b ON b.name = r.bank_transaction
        SET
            r.settlement_number = b.settlement_number,
            r.settlement_date = b.settlement_date,
            r.pos_reconciliation_number = b.pos_reconciliation_number,
            r.bank_commission_amount = COALESCE(b.fee_amount, 0),
            r.bank_commission_vat_amount = COALESCE(b.vat_amount, 0),
            r.bank_settlement_amount = COALESCE(b.settlement_amount, 0)
        WHERE r.bank_transaction IS NOT NULL AND r.bank_transaction != ''
        """
    )

    # Initialize Finance review status. Existing manual clearances stay approved.
    frappe.db.sql(
        """
        UPDATE `tabPOS Reconciliation Record`
        SET finance_review_status = CASE
            WHEN match_status = 'Bank Only' AND resolution_status = 'Manually Cleared' THEN 'Checked & Approved'
            WHEN match_status = 'Bank Only' THEN 'Pending Review'
            ELSE 'Not Required'
        END
        """
    )

    if frappe.db.exists("DocType", "POS Bank Manual Clearance"):
        frappe.db.sql(
            """
            UPDATE `tabPOS Reconciliation Record` r
            INNER JOIN `tabPOS Bank Manual Clearance` c ON c.bank_transaction = r.bank_transaction
            SET
                r.finance_review_status = CASE
                    WHEN c.finance_review_status IN ('Checked & Approved', 'Needs Investigation')
                        THEN c.finance_review_status
                    WHEN c.active = 1 THEN 'Checked & Approved'
                    ELSE r.finance_review_status
                END,
                r.finance_review_note = c.finance_review_note,
                r.finance_reviewed_by = c.finance_reviewed_by,
                r.finance_reviewed_on = c.finance_reviewed_on
            WHERE r.match_status = 'Bank Only'
            """
        )

    # Seed the Company in the Single settings DocType from Global Defaults when
    # available. Accounts and POS Profile mappings are deliberately left for
    # Finance to configure before the future GL-posting phase.
    if frappe.db.exists("DocType", "POS Reconciliation Settings"):
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if company and not frappe.db.get_single_value("POS Reconciliation Settings", "company"):
            frappe.db.set_single_value("POS Reconciliation Settings", "company", company)

    frappe.clear_cache()
