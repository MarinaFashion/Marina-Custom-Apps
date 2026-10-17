# POS Reconciliation v0.53.1 — Single Controller (Experimental)

## Design
* `POS Reconciliation Run` is a **Single** control document. It is not an audit-log document and cannot create numbered runs.
* `POS Reconciliation Execution` is an immutable-scope execution log: dates, filters, user, queue/run/error status and summary.
* `POS Reconciliation Record` remains a **normal** DocType. Canonical unique identity is `BANK|<Bank POS Transaction name>` if a bank transaction is present, otherwise `ALHAMRANI|<Alhamrani name>`. `record_key` remains unique, and generated `name` hashes it.
* The engine upserts only source transactions selected by the current execution. It never deletes out-of-scope results; transitions from unmatched Alhamrani records to bank-backed results remove only the superseded source result after checking linked posting/settlement evidence.
* Finance-reviewed and accounting-posted results cannot be silently rematched. Bank-statement processing is restricted to the scope's settlement groups. Accounting synchronization is restricted to the bank transactions just processed.
* Existing `run`, `source_run`, and `reconciliation_run` fields are retained as **Data**, not Link to a Single (Singles have no normal table row). Their only new value is `POS Reconciliation Run`.
* `POS Reconciliation Period Lock` preserves period-level closing independently of the Single controller. Closed periods block execution, Finance review, manual clearance and accounting submission. For safety, global closing requires a completed all-profile/all-card execution fully covering the dates.

## Mandatory pre-migration conditions
**Do not deploy without a database backup.** The pre-model-sync patch refuses conversion if it sees:
- Any `POS Reconciliation Record`, `POS Accounting Posting` (including drafts), or `POS Bank Settlement` and their related child rows.
- Any Bank Statement source already linked to a POS Reconciliation Run.
- Any Bank POS Transaction linked to an accounting posting or Journal Entry.
- Any old POS Reconciliation Run that is Queued/Running.

Existing old numbered Run rows are left in the legacy normal table for rollback, but are no longer operational after converting the DocType to Single.

## Install / upgrade on Demo **only**
1. Confirm preconditions in **marinademo.frappe.cloud** and take full DB backup.
2. Deploy experimental commit, run `bench --site marinademo.frappe.cloud migrate`, and clear cache.
3. Confirm `POS Reconciliation Run` meta `issingle=1`, a Single route and new Execution / Period Lock DocTypes.
4. Execute 1–15 October, then 10–25 October with overlapping source rows, then 1–31 October. The number of current records should match distinct Bank POS source names plus distinct unmatched Alhamrani source names. Each repeated transaction must retain one record ID, not create a new ID.
5. Reconcile a disjoint later date range; assert prior period rows are unchanged.
6. Create and verify a matched statement settlement and ensure another profile/period's Bank Statement links are untouched.
7. Verify pending/approved Finance review persists across an unchanged rerun. Verify a changed approved/posted source blocks with a clear error.
8. Verify accounting posting occurs at most once per Bank POS Transaction. Verify the existing cross-transaction locking and duplicate-posting protections.
9. Verify a closed financial period rejects reconciliation and Finance/accounting actions; reopening with a reason restores operation.
10. Verify two users cannot queue concurrently, and that editing Single form inputs while a job is running never changes the execution's recorded scope.

**Do not merge into main or deploy Live based solely on static code inspection.** ERPNext/Frappe runtime tests are required first.

## Rollback
Do not blindly switch DocType JSON back once Single results have been created. If Demo migration fails before running new jobs, restore the database backup and the previous experimental commit together. After any job or posting, prepare a specific data rollback plan rather than attempting an in-place reversal. The preflight does not destroy old numbered Run rows.
