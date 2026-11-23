# Marina Leave Reconciliation — read-only report

## Demo deployment
Deploy `feature/marina-leave-management` on
`marinademo.frappe.cloud` and run the normal Frappe Cloud migration.
Open **Marina Leave Reconciliation** from ERPNext Report List or directly:
`/app/query-report/Marina%20Leave%20Reconciliation`.

Requires HR Manager or System Manager and read access to Employee and
Leave Application. Report provides As Of, Employee, Contract Entitlement,
and Show Exempt Employees filters.

## Important limitations
- This is a **provisional simulation**, not an official Leave Balance report.
- 30/330 and 21/339 standardized eligible-day formulas are still subject
  to HR/legal validation, including annual service caps and excluded leave.
- The simulation assumes the current contract entitlement applies from
  joining date; historic 21-to-30 transitions cannot yet be reconstructed.
- Calendar-day exclusions may differ from leave days defined by an ERPNext
  Holiday List; preview warnings highlight obvious discrepancies.
- Only submitted **Approved** Paid Leave and Leave Without Pay exclude
  accrual; rejected applications do not.
- Credits and debits are summarized using ledger effective dates. Paid Leave
  ledger debits spanning the cutoff are flagged and omitted in full.
- The known test allocation `HR-LAL-2024-00001` is excluded entirely,
  including both +73 and -50 ledger entries. Original records remain intact.
- Leave taken outside ERPNext may be absent from historical data.
- Long-service employee calculations require historical contract and leave
  record verification. Proposed credits must NOT be posted automatically.
- HR exemptions are managed via Employee field
  `custom_exclude_from_leave_accrual`, NOT by job title or remote status.
  Exempt records show **no calculation**, not a zero balance.
- `Provisional Unposted Credit` = simulator earned - non-test ledger
  credits recognized in preview. It is NOT an approved accounting adjustment.
- `Indicative Balance` = simulator earned + recognized ledger application
  debits. It is NOT the ERPNext period-specific available leave balance.

## Demo smoke tests
1. Verify report loads without SQL/write errors, and only authorized roles
   can view. Check filtering for Annual 21 and Annual 30.
2. Mark HR-EMP-00048 and HR-EMP-00023 exempt **manually** only after HR
   confirms. Verify blank earned/balance and Exempt status.
3. Check HR-EMP-00018 and HR-EMP-00010 against previous simulations.
4. Inspect notes for ledger spanning cutoff, older records, holidays and
   historical contract changes.
5. Run regression tests in a bench console:

```python
import unittest
from marina_custom_apps.marina_custom_apps.report.marina_leave_reconciliation import test_marina_leave_reconciliation
suite = unittest.defaultTestLoader.loadTestsFromModule(test_marina_leave_reconciliation)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(result.testsRun, len(result.failures), len(result.errors))
```

## Release gate
No scheduler, no leave allocation, no historical credit posting.
Review business formula and employee history before authorizing changes.
