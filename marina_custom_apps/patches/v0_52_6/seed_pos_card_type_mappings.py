import frappe

SETTINGS_DOCTYPE = "POS Reconciliation Settings"
DEFAULT_MAPPINGS = [
    ("P1", "MADA", "MADA"), ("MADA", "SPAN", "MADA"), ("SPAN", "P1", "MADA"),
    ("VC", "VISA", "VISA"), ("VISA", "VC", "VISA"),
    ("MC", "MASTER_CARD", "MASTERCARD"), ("MASTER_CARD", "MASTER CARD", "MASTERCARD"),
    ("MASTER CARD", "MASTERCARD", "MASTERCARD"), ("MASTERCARD", "MC", "MASTERCARD"),
    ("GCCCARD", "GCC CARD", "GCC CARD"), ("GCC_CARD", "GCCCARD", "GCC CARD"),
    ("GCC CARD", "GCC_CARD", "GCC CARD"),
    ("AMEX", "AMERICAN E", "AMERICAN EXPRESS"),
    ("AMERICAN_EXPRESS", "AMERICAN EX", "AMERICAN EXPRESS"),
    ("AMERICAN EXPRESS", "AMERICAN_EXPRESS", "AMERICAN EXPRESS"),
    (None, "AMERICAN EXPRESS", "AMERICAN EXPRESS"), (None, "AMEX", "AMERICAN EXPRESS"),
]

def execute():
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE) or not frappe.db.exists("DocType", "POS Card Type Mapping"):
        return
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    if settings.get("card_type_mappings"):
        return
    for bank, alhamrani, unified in DEFAULT_MAPPINGS:
        settings.append("card_type_mappings", {"bank_card_type": bank, "alhamrani_card_type": alhamrani, "unified_card_type": unified})
    settings.save(ignore_permissions=True)