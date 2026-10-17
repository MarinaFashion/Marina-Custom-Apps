# v0.53.3 — Bank Statement: POS Profile and Linked Reconciliation Records

Experimental branch: `feature/v0.53.0-snb-bank-statement-reconciliation`. Do **not** deploy Live or merge main until Demo verification.

## Features

When a `Marina Bank Statement Transaction` is linked to a fully reconciled `POS Bank Settlement`:

- `POS Profile` is displayed on the statement form as a read-only Link, only if all eligible contributing POS Reconciliation Records have the **same known profile**. It remains empty if the settlement combines multiple profiles or includes unknown/unsupported sources.
- `Contributing POS Reconciliation Records` child table lists each eligible POS Reconciliation Record **once per statement row**, with a clickable ERPNext Link ID, its POS Profile, and its current settled match status.
- Source status `Fully Matching` is displayed as **Fully Matched**, while `Bank Only - Settled` remains unchanged. Unsettled or discrepancy source records are never presented as settled.
- These details are **settlement-level**: a settlement may have separate Gross, Commission and VAT lines. Each participating bank statement line shows the POS records contributing to the same settlement.
- Only reconciled statement rows receive linked POS records; partially reconciled records receive no eligible settled details.
- If a rerun changes or removes a link in the selected scope, the read-only child table and POS Profile are recalculated or cleared. Statement rows outside the selected execution scope are untouched.
- The system uses chunked queries and bulk updates, not one query per statement/record. Unchanged data is not rewritten. The table is a derived convenience projection, not accounting evidence.

## Deployment (Demo only)

1. Take a Demo database backup.
2. Deploy the v0.53.3 experimental commit and run `bench --site marinademo.frappe.cloud migrate` if Frappe Cloud does not migrate automatically.
3. Run `bench --site marinademo.frappe.cloud clear-cache`, then hard-refresh the browser.
4. Rerun `POS Reconciliation Run` Single with an explicit Bank Account and a **small** previously reconciled date range first. Rerun is needed to populate the new columns and child rows for existing bank statements; migration alone does not backfill all history.
5. Open a reconciled `Marina Bank Statement Transaction` with a `pos_bank_settlement` link. Verify POS Profile and child rows.
6. Click a POS Reconciliation Record ID and verify it opens the original record; compare status and POS Profile to the record itself.
7. Verify a settlement containing multiple POS records shows multiple child rows. For a settlement with different profiles, the statement's main POS Profile must be blank, and each child row must show the accurate profile.
8. Rerun the **same dates** and verify no duplicate child links are created. Reconcile an overlapping period and ensure a previously populated statement outside the period is unchanged.
9. Check that a Bank/GL-only or unreconciled statement row does **not** show invented POS details, and that no Journal Entries or Bank POS source records were changed.
10. Do not merge to main until full Demo tests and accounting checks pass.

## Audit / data-model considerations

The new `Marina Statement POS Record` is a standard Frappe child DocType with a Link to `POS Reconciliation Record` and a Link to `POS Profile`. These child links are derived from `POS Bank Settlement.transactions`; they do not create new GL postings or accounting allocations.

As with existing POS settlement child links, deleting an underlying POS Reconciliation Record while a statement references it may be blocked by Frappe link validation. Use a controlled unlink/reset workflow when clearing test data. **Never force-delete linked accounting evidence on Live.**
