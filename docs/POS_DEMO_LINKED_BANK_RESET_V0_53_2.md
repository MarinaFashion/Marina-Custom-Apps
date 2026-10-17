# Marina Custom Apps v0.53.2 — Demo Linked Bank Statement Reset

This enhancement is for **marinademo.frappe.cloud only**. It is added to experimental Single-DocType branch `feature/v0.53.0-snb-bank-statement-reconciliation`. It does not merge or deploy to main/Live.

## Why

A Bank Statement Reconciliation Match contains Bank rows linking to Marina Bank Statement Transactions, while the statement transaction stores a Link back to the Match. POS Bank Settlements and their Statement Match child rows create another circular link. Native Delete can fail on either side.

## Scope of destructive reset

Only transactions with current **POS reconciliation** or **Bank/GL match** associations are eligible. The reset finds the union of:
- Statement Transactions whose `pos_bank_settlement`, `pos_reconciliation_run`, or `bank_statement_reconciliation_match` field is populated;
- All `Bank Statement Reconciliation Bank Row.statement_transaction` references;
- All `POS Bank Settlement Statement Match.bank_transaction` references.

The following are **deleted** after releasing circular dependencies:
- These linked **Marina Bank Statement Transaction** imported source rows;
- All affected **Bank Statement Reconciliation Match** groups, including their Bank/GL child rows.

The following are **preserved**:
- Imported **Bank POS Transaction** source rows, accounting GL Entries, Payment Entries, Journal Entries and bank accounts;
- Unlinked Marina Bank Statement Transactions;
- Marina Bank Statement Import batch documents and their import files;
- POS Bank Settlement and POS Reconciliation Record documents, whose statement-specific evidence is **reset**, not deleted.

Deleting a Bank/GL Match releases its GL Entry references for later matching; it does not edit GL accounting entries. Historical Import batch counters may continue to reflect the original import, even though linked source rows have been deleted.

## Safety

- Preview lists exact counts and blockers. A System Manager must type `DELETE DEMO LINKED BANK STATEMENTS` to queue the job.
- The server validates the exact Demo site and requires `POS Reconciliation Run` to be a Single DocType.
- Reruns preflight and confirms the immutable inventory hash under database row locks before deleting.
- Refuses to run if accounting postings or Journal Entries exist, protected Finance-reviewed/posted evidence is linked, a statement allocation or exclusion references targeted rows, a required referenced document is missing, or the POS Single execution is queued/running.
- The entire deletion runs as one database transaction; any unexpected Frappe link-check failure rolls it back.
- Never bypasses Frappe's link validation with `force=True`; the utility uses narrowly authorized document deletion.
- The reset does not restore imported rows automatically. Restore the Demo database backup if the reset needs to be reversed.

## Demo test

1. Take a complete **Demo database backup** and stop POS/Bank Statement reconciliation work during cleanup.
2. Deploy the experimental branch with the v0.53.2 cleanup commit to Demo and run `bench --site marinademo.frappe.cloud migrate` / `clear-cache` if needed.
3. Open **Marina Bank Statement Transaction → List** as System Manager.
4. Select **Preview Demo Linked Reset**; review counts carefully. This targets linked **source rows**, not merely reconciliation status.
5. If any blocker appears, stop and share it. Do not manually force-delete.
6. If counts are correct, type the exact confirmation phrase and queue the long worker.
7. Use **Check Demo Reset Status** until `Completed`. A `Failed` result requires investigating the error before retrying.
8. Verify:
   - `Bank Statement Reconciliation Match` count = 0.
   - All circular-linked statement rows in the defined scope are gone.
   - GL Entries, Bank POS Transactions, unlinked statements and import batch records remain.
   - POS Reconciliation Record statement links/status are reset, and POS Bank Settlements have no Statement Match children.
9. Re-import desired Bank Statement files (the importer deduplicates by `source_key` against currently existing transactions) and rerun Single POS Reconciliation.
10. Test overlapping date ranges and confirm canonical POS Reconciliation Record IDs remain stable.

**Not a general production deletion method.** A future production enhancement should use audited reversal/cancellation rather than destructive deletion.
