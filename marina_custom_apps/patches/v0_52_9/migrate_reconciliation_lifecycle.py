import frappe

def execute():
    if not frappe.db.exists("DocType","POS Reconciliation Run"):
        return
    frappe.db.sql("""
        UPDATE `tabPOS Reconciliation Run`
        SET status='Open'
        WHERE status IN ('Completed','Running')
    """)
    if frappe.db.has_column("POS Reconciliation Run","execution_status"):
        frappe.db.sql("""
            UPDATE `tabPOS Reconciliation Run`
            SET execution_status='Idle'
            WHERE execution_status IS NULL OR execution_status='' OR execution_status='Running'
        """)