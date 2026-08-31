"""Shared Material Request lifecycle fan-out for Marina planning modules."""

def on_trash(doc, method=None):
    from marina_custom_apps.dc_dispatch.material_request_events import clear_proposal_links as dc_clear
    dc_clear(doc, method=method)
    from marina_custom_apps.stock_auto_allocation.material_request_events import on_trash as allocation_trash
    allocation_trash(doc, method=method)
