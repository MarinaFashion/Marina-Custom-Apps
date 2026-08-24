# Marina Custom Apps

Umbrella Frappe/ERPNext custom application for Marina Trading Company.

## Modules

### Stock Transfer Control
Central policy layer for:
- Send Stock / Receive Stock / Transfer Between
- role hierarchy and Warehouse Users Allowed
- Physical ↔ Transit warehouse validation
- Material Request → Stock Entry policy
- End Transit foundation
- physical receipt vs ledger quantity reconciliation

### Stock Transfer Audit
Planned settlement layer for:
- date-window audit runs
- line-level transfer discrepancies
- Return Discrepancy to Source
- Send Discrepancy to Target
- corrective Stock Entry traceability

## Version 0.2.0

v0.2.0 adds the backend policy foundation and reconciliation custom fields.
It intentionally does **not** activate Stock Entry validation hooks yet. This
allows the new policy layer to be reviewed against Marina's existing Stock
Entry client/server scripts before enforcement is switched on.
