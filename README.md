# Marina Custom Apps

Umbrella Frappe/ERPNext custom application for Marina Trading Company.

## Modules

### Stock Transfer Control
Central policy layer for:
- Send Stock / Receive Stock / Transfer Between
- role hierarchy and Warehouse Users Allowed
- Physical ↔ Transit warehouse validation
- Material Request → Stock Entry control
- End Transit foundation
- physical receipt vs ledger quantity reconciliation

### Stock Transfer Audit
Planned settlement layer for:
- date-window audit runs
- line-level transfer discrepancies
- Return Discrepancy to Source
- Send Discrepancy to Target
- corrective Stock Entry traceability

## Version 0.3.0

v0.3.0 activates the central Stock Entry route-control layer.

Key principles:
- Manual Stock Entries default to Send Stock.
- Sales Supervisor can manually use Send Stock only.
- Warehouse Manager can use Send Stock and Physical → Physical Transfer Between.
- Stock Manager / Administrator can also use the temporary broader Transfer Between correction path.
- Receive Stock cannot be manually created.
- Material Request → Stock Entry is always controlled as Send Stock and the MR route cannot be rewritten.
- Child-row warehouse routes are locked to the Stock Entry header.
- Server validation is authoritative; client logic is only for UX.
- Send Stock cannot be cancelled while a submitted linked Receive Stock exists.

End Transit creation and receiving-method workflow are intentionally scheduled for the next phase.
