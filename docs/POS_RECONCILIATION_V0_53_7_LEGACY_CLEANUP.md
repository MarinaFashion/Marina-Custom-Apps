# Marina Custom Apps v0.53.7 — POS Legacy DocType Retirement

## Objective

Remove obsolete POS reconciliation controls left by the previous architecture. This is a
**guarded metadata cleanup**, not a reset of completed reconciliation work.

### Removed (only when empty)

| Legacy DocType | Live inventory before development |
| --- | ---: |
| POS Bank Manual Clearance | 0 |
| POS Bank Statement Reconciliation | 0 |
| Marina Bank Statement Allocation | 0 |

The `allocations` child-table field and its empty section were removed from
`Marina Bank Statement Transaction`. Historical manual-clearance Python services,
list-view approval/reset buttons, and the old POS-only statement controller were retired.
A persisted shortcut to `POS Bank Manual Clearance` is removed from the POS Workspace.

### Retained — never cleared by this update

- `Bank POS Transaction` and `Marina Bank Statement Transaction` imports.
- Alhamrani terminal source transactions, Terminal References, mappings and settings.
- `POS Reconciliation Record`, `POS Bank Settlement`, settlement child tables and
  `Marina Statement POS Record` links.
- `POS Accounting Posting`, its items, Bank POS accounting links and Journal Entries.
- `POS Reconciliation Execution`, `POS Reconciliation Period Lock`, Single Run control.
- **`Bank Statement Reconciliation`** (general-bank controller), its match records,
  and the Bank Row / GL Row child DocTypes.
- Historical Finance status fields *already stored on active reconciliation records*;
  these remain protected by the engine's existing Finance/accounting review guard.

### Safety and migration

1. Verify a restorable database and files backup before any deployment (especially Live).
2. Do not run a reconciliation execution concurrently with migration.
3. The `pre_model_sync` patch `v0_53_2.preflight_legacy_cleanup` refuses migration if
   **any** of the three legacy tables has even one record, or a POS execution is
   Queued/Running. This applies independently to Demo and Live.
4. The `post_model_sync` patch `v0_53_2.retire_legacy_doctypes` repeats the safety
   checks, verifies no remaining Link/Table schema references, cleans persisted
   Workspace shortcuts and retires the three DocType definitions via Frappe's API.
5. Do not bypass a failed guard using `--skip-failing`, `DROP TABLE`, `DELETE`,
   or a force migration. Inspect the named legacy table, preserve any meaningful
   audit evidence, and resolve the condition deliberately before retrying.
6. Deploy to Demo, run migration normally and check all POS and general-bank functions.
   Deploy the **same verified commit** to Live only after Demo acceptance.

### Demo smoke tests

- Confirm the three obsolete DocTypes are absent; check that the general
  `Bank Statement Reconciliation` controller still opens.
- Confirm all imported bank and statement records are unchanged.
- Re-run a small POS period and then an overlapping period. Check stable canonical
  PREC identifiers, settled/exception classifications and statement POS child links.
- Re-run September only after examining existing Finance review/accounting exceptions;
  do not override review or posting protection.
- Confirm POS imports, POS Profile locations, Terminal History, reports, Dashboard,
  accounting preview and draft/submitted Journal Entries remain intact.
- Confirm both Bank POS Transaction and POS Reconciliation Record lists no longer
  offer obsolete manual-clearance/Finance-review buttons.
- Confirm the POS Workspace contains no old manual-clearance shortcut and the
  active general-bank reconciliation Workspace shortcut opens.
- Check `POS Reconciliation Execution` for Completed status and no uncaught
  background exceptions.

### Regression tests (run on Demo if test runner available)

```bash
bench --site marinademo.frappe.cloud run-tests \
    --module marina_custom_apps.pos_reconciliation.tests.test_pos_legacy_cleanup
```

**Release code has been reviewed for structure and JavaScript syntax; a full Frappe
runtime test and site migration must be done in Demo before Live.**

### Recovery

If the preflight fails, no cleanup occurs; inspect the named table and backup.
If a deployment later needs rollback, restore the verified database/files backup
and the corresponding prior application revision together. Do not reinstall the
old DocTypes against the new database without a migration plan.
