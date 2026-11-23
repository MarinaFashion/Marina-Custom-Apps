# Marina Leave Accrual Batch — Phase 4A (approval preview only)

**Branch:** `feature/marina-leave-management`

This release introduces two standard Frappe DocTypes:
- **Marina Leave Accrual Batch** (company + completed calendar month end)
- **Marina Leave Accrual Batch Employee** (read-only calculated child lines)

## Workflow (intentionally pre-posting)

1. HR Manager/System Manager creates a new batch with Company and **Month-End Credit Date** (for example `2026-10-31`) and saves.
2. The system generates a deterministic unique batch key per company and month. A second batch for the same company/date is blocked by the unique key; not a second credit.
3. Select **Generate / Refresh Candidates**. Employee figures are calculated using the existing `monthly_preview.get_candidates` and the tested `accrual.simulate`. Status becomes **Calculated**; no HRMS allocations are written.
4. Review each employee, eligible/excluded days, suggested credit and warnings. Exempt employees are excluded.
5. Select **Approve Preview Batch**. The server **recalculates all employees** and verifies each material candidate signature, employee count, and missing/error statuses. Any changed candidate requires regeneration; warning rows require explicit confirmation. Status becomes **Approved**; still NO ledger posting.
6. Approved batches cannot be regenerated or manually edited through normal document save actions.

An approved batch is a *planning approval only*. It is NOT permission to modify Leave Allocations. Posting API, scheduler and automatic HRMS adjustments are deliberately absent.

## Access

- HR Manager and System Manager have Read/Create/Write permissions.
- Each server-side mutation checks the acting user's role again.
- Generation uses only active Full-time Annual 21 / Annual 30 employees of the batch company.
- Source employee leave application access is checked in the preview.
- No auto scheduler and no hooks are added.
- A unique batch key on company + credit month prevents duplicate batches. Separate posting idempotency by employee/date will be essential in the future posting phase.

## Demo smoke test

Deploy this branch and migrate the demo. Open:
`/app/marina-leave-accrual-batch`

- Create a batch for the company's **last completed month end**.
- Generate candidates and confirm the employee count, positive candidate amounts, zero-accrual employees and review warnings.
- Verify HR-EMP-00007's October 2026 calculation against the approved accrual formula.
- Try creating a second batch with the same company and month; expect a duplicate-key rejection.
- Approve the batch and confirm status **Approved**, with **no new Leave Allocation or Leave Ledger Entry**.
- Verify an older batch cannot be approved if the source leaves or entitlement changed without regenerating.
- Verify employees marked `custom_exclude_from_leave_accrual` are absent.
- Verify unauthorized users cannot create, generate or approve.

## Focused bench-console regression

```python
import unittest
from marina_custom_apps.marina_custom_apps.doctype.marina_leave_accrual_batch import test_marina_leave_accrual_batch
suite = unittest.defaultTestLoader.loadTestsFromModule(test_marina_leave_accrual_batch)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print("Tests:", result.testsRun, "Failures:", len(result.failures), "Errors:", len(result.errors))
```

## Before enabling real posting

- Validate standard HRMS **Leave Allocation** compatibility, especially earned leave auto-credit, precision, allocation period effective dates, and historical credits.
- Require per-employee/per-month idempotency and a recovery strategy for partially completed batches.
- Decide historical opening-balance cutover date to prevent retroactive double credit.
- Confirm permissions, audit trail, and failure rollback at the posting boundary.
- Ensure December 31 accounting valuation is independent of whether a delayed scheduler completes during the following month.

**Scope:** Custom batch documents may be saved in the database; no standard Employee, Leave Allocation or Leave Ledger records are changed by batch actions.
