import frappe

def execute():
    if not frappe.db.exists("DocType","POS Reconciliation Run"):
        return
    # Historical patch must not try to UPDATE a table when Run is a Single.
    if frappe.db.get_value("DocType", "POS Reconciliation Run", "issingle"):
        return
    if not frappe.db.table_exists("POS Reconciliation Run"):
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