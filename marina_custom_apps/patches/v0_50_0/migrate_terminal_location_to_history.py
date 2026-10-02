import frappe


def execute():
    """Move legacy Terminal Reference address into the active location-history row.

    Branch Name is intentionally not copied: POS Profile is the authoritative store/location
    reference. Existing database columns are left intact by Frappe schema migration, so legacy
    values remain recoverable even after the parent fields are removed from the DocType UI.
    """
    if not frappe.db.table_exists("Terminal Reference"):
        return
    if not frappe.db.has_column("Terminal Reference", "address"):
        return
    if not frappe.db.table_exists("Terminal Location History"):
        return
    if not frappe.db.has_column("Terminal Location History", "address"):
        return

    terminals = frappe.db.sql(
        """
        select name, address
        from `tabTerminal Reference`
        where coalesce(address, '') != ''
        """,
        as_dict=True,
    )

    for terminal in terminals:
        rows = frappe.get_all(
            "Terminal Location History",
            filters={
                "parent": terminal.name,
                "parenttype": "Terminal Reference",
                "parentfield": "locations",
            },
            fields=["name", "address", "to_date", "idx"],
            order_by="from_date asc, idx asc",
            limit_page_length=0,
        )
        if not rows:
            continue

        active_rows = [row for row in rows if not row.to_date]
        targets = active_rows if active_rows else ([rows[-1]] if len(rows) == 1 else [])

        for row in targets:
            if not row.address:
                frappe.db.set_value(
                    "Terminal Location History",
                    row.name,
                    "address",
                    terminal.address,
                    update_modified=False,
                )
