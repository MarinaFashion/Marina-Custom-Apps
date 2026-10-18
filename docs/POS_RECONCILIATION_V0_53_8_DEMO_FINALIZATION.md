# Marina Custom Apps v0.53.8 — Demo Legacy Cleanup Finalization

## Why this follow-up patch exists

The v0.53.7 migration removed the three obsolete POS reconciliation DocType
definitions on Demo. Its pre-/post-model-sync cleanup patches **were skipped**
because a historical row remained in the *physical* SQL table
`tabPOS Bank Statement Reconciliation`.

Read-only Demo evidence (October 18, 2026):

- Old run: `POS-BANK-REC-2026-00001`, Completed, created October 14
- Period: September 20 to October 15, 2026
- 176 settlement groups; 67 fully reconciled; 109 exceptions; 2,426 statement lines
- Direct links to this old run in `POS Bank Settlement.reconciliation_run`,
  `POS Reconciliation Record.bank_statement_reconciliation` and
  `Marina Bank Statement Transaction.pos_reconciliation_run`: **zero**
- Physical tables for the other two retired DocTypes were empty.
- The older `v0_53_2` patch logs show `skipped=1` and must not be edited manually.

## What the new patch does

`marina_custom_apps.patches.v0_53_3.finalize_legacy_cleanup`, registered
**post-model-sync**, checks:

1. No active/queued `POS Reconciliation Execution` job.
2. All three target DocTypes are unregistered.
3. No Link/Table customizations refer to a retired DocType.
4. The two other legacy physical tables contain zero rows.
5. The retired statement run table has **no more than 10 rows**.
6. Each remaining old statement-run record has no direct links in the three
   active source/output tables described above.

It then exports **every column of each old statement-run row** to a private JSON
`File` attached to the Single `POS Reconciliation Run`. A SHA-256 checksum
is included in the deterministic file name. The archive is re-read and its
content checksum verified **before** the three old SQL tables are dropped.
The patch is idempotent for a partial failed attempt.

The migration also cleans legacy Workspace references and removes the old
`execute_statement_reconciliation` service entrypoint for the retired POS-only
controller; shared parsing/settlement helpers used by the current unified
reconciliation remain available.

## What must not change

All imported Bank POS, Alhamrani and Marina Bank Statement data; existing
`POS Reconciliation Record`, `POS Bank Settlement`, child links,
`POS Accounting Posting`, Journal Entries, account ledgers, and
`Bank Statement Reconciliation` (general-bank) remain untouched.

## Demo acceptance procedure

1. Verify a restorable Demo database/files backup.
2. Deploy the new GitHub revision and let normal migration complete. **Never
   use `--skip-failing` to bypass an active new patch failure.**
3. Confirm the new patch's `Patch Log.skipped` is `0`.
4. Confirm all three retired SQL tables are absent.
5. Find the private archive through **File** records whose filename starts
   `marina-pos-legacy-statement-runs-` and verify the old run is preserved.
6. Execute a small-period POS reconciliation and an overlapping rerun; check
   stable record IDs, settlement status, and statement links.
7. Validate general-bank statement reconciliation, dashboard, imports,
   accounting preview, and existing Journal Entries.
8. Share unexpected errors before deploying to Live.

A skipped historical `v0_53_2` patch log may remain; validation is based on the
new `v0_53_3` patch and the actual database state. Do not edit Patch Log
records.

## Runtime test

```bash
bench --site marinademo.frappe.cloud run-tests \
  --module marina_custom_apps.pos_reconciliation.tests.test_legacy_archive_finalization
```

A GitHub/source review does not replace these Demo runtime and data checks.
