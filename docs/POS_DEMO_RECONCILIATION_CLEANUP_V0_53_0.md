# v0.53.0 — Demo-only legacy POS reconciliation cleanup

This change is **not** the v0.53.1 Single-DocType migration. The cleanup branch is based on main v0.53.0 and can be deployed to Demo separately.

## What it does

The old code creates circular links:
- `Marina Bank Statement Transaction.pos_bank_settlement` → `POS Bank Settlement`;
- `POS Bank Settlement.statement_matches[].bank_transaction` → `Marina Bank Statement Transaction`;
- `POS Reconciliation Record.bank_statement_settlement` → `POS Bank Settlement`;
- `POS Bank Settlement.transactions[].reconciliation_record` → `POS Reconciliation Record`.

These links make normal deletion fail. An explicit **Demo-only** maintenance utility is added to the `POS Bank Settlement` list:
1. **Preview Demo POS Cleanup**: shows counts, potential blockers and source records preserved.
2. **Check Demo Cleanup Status**: shows Queued, Running, Completed, or Failed after requesting cleanup.

A System Manager must review the preview and type `CLEAR DEMO POS RECONCILIATION` exactly. The cleanup is then queued to Frappe's **long worker**. It rechecks the data fingerprint and all safety blockers immediately before mutation.

The utility unlinks only POS-generated reconciliation references on imported Bank Statement Transactions, restores their unallocated status, clears reciprocal links from POS Reconciliation Records, then deletes all old derived `POS Bank Settlement`, `POS Reconciliation Record` and `POS Bank Manual Clearance` test documents in one database transaction. Parent settlement deletion removes associated child rows. It does **not** delete imported `Bank POS Transaction`, `Marina Bank Statement Transaction`, or source import batches. It does **not** delete old numbered `POS Reconciliation Run` documents.

Safety blockers stop cleanup if POS Accounting Posting records or items, Journal Entry links, drafted/posted accounting status, Bank/GL reconciliation allocations, non-POS linked statement rows, excluded statement rows, missing settlement link targets, or active old reconciliation jobs are found. An unexpected extra link causes normal Frappe link validation to fail and the worker to roll back.

## Demo steps

1. Take a **full Demo database backup**, ensuring it can be restored.
2. Deploy **only** branch `fix/v0.53.0-demo-reconciliation-cleanup` to `marinademo.frappe.cloud`. Do **not** deploy v0.53.1 Single yet.
3. Run `bench --site marinademo.frappe.cloud migrate` and `bench --site marinademo.frappe.cloud clear-cache`.
4. Log in as **System Manager** and open **POS Bank Settlement** List.
5. Click **Preview Demo POS Cleanup**. If blocked, do not force-delete documents. Resolve the identified accounting or source dependency first.
6. After reviewing counts and the backup, confirm the exact phrase. The maintenance job runs on the long worker.
7. Click **Check Demo Cleanup Status** until **Completed**. If Failed, no partial cleanup should have been committed; review the server error and restore the backup if needed.
8. Verify in Demo console:

```python
import frappe

for doctype in (
    "POS Bank Settlement",
    "POS Reconciliation Record",
    "POS Bank Manual Clearance",
    "POS Accounting Posting",
):
    print(doctype, frappe.db.count(doctype))

print("Imported POS source:", frappe.db.count("Bank POS Transaction"))
print("Imported statement source:", frappe.db.count("Marina Bank Statement Transaction"))

print("Remaining POS settlement links:", frappe.db.sql("""
    SELECT COUNT(*) FROM `tabMarina Bank Statement Transaction`
    WHERE COALESCE(pos_bank_settlement, '') <> ''
       OR COALESCE(pos_reconciliation_run, '') <> ''
""")[0][0])
```

9. Report the counts and confirm all derived records were cleared. Only then will the Single architecture be prepared for deployment.

## Notes

- This is **destructive only to Demo's derived test reconciliation records**. It should never be installed/run on Live. The backend validates the site name `marinademo.frappe.cloud` and System Manager role regardless of any UI restriction.
- Do not run a POS reconciliation or post accounting while the cleanup is queued/running.
- Use a database restore, not an in-place reverse script, for rollback.
- If the long worker failed, do not attempt manual SQL deletion without investigating the blocker.
