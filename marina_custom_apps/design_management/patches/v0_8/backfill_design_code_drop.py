"""Backfill existing Design Codes with Drop from their linked Mood Board.

Runs after DocType sync so the Design Code Drop column already exists.
Does not touch modified timestamps or milestone/production child rows.
"""
import frappe


def execute():
    last = ""
    while True:
        batch = frappe.get_all("Design Code",
            filters={"name": [">", last]},
            fields=["name", "mood_board"],
            order_by="name asc", limit_page_length=200)
        if not batch:
            break
        board_ids = sorted({row.mood_board for row in batch if row.mood_board})
        drops = {row.name: row.drop for row in frappe.get_all(
            "Mood Board", filters={"name": ["in", board_ids]},
            fields=["name", "drop"], limit_page_length=len(board_ids)
        )} if board_ids else {}
        for row in batch:
            if row.mood_board in drops:
                frappe.db.set_value("Design Code", row.name, "drop",
                    drops[row.mood_board], update_modified=False)
        last = batch[-1].name
