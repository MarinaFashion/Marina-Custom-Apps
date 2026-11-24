# Marina Leave Posting Journal — schema & precision stage

This change establishes the structure for **future** safe month-end HRMS posting.
It DOES NOT contain a method to create HRMS Leave Allocations or Leave Ledger
Entries, nor a scheduler or enabled posting setting.

## Verified demo constraints
- HRMS 15.64.9
- Paid Leave: `is_earned_leave=1`; monthly earned-leave scheduler running
- Leave Allocation `new_leaves_allocated` and `total_leaves_allocated`:
  effective precision 3
- No Leave Policies / Assignments; existing historic test allocation
  `HR-LAL-2024-00001` must remain untouched

## Journal
A standard ERPNext DocType `Marina Leave Posting Journal` is read-only to HR
Manager and System Manager. Every entry is scoped to company + employee +
leave type + month-end credit date, with a **unique deterministic posting key**.
Its exact accrual and rounding residual values are stored as 6-decimal strings,
not HRMS Float fields, to avoid losing precision.

No journal creation/update API is available. The controller rejects normal
inserts or saves until a future server-authorized posting service is built.

## Cumulative residual model
Each period:
- exact = 6dp monthly amount from the verified accrual engine
- three-decimal HRMS credit = round(exact + previously **posted** residual, 3dp)
- closing residual = exact + opening residual - HRMS credit
- only committed, verified posting can advance the residual
- zero-credit months do not create a leave allocation

Example: 2.776119 => 2.776 posted, residual +0.000119.
Next month 2.686567 => 2.687 posted, residual -0.000314.
Total posted + final residual = total calculated (subject to 6dp precision).

## Next gate
Inspect actual installed `hrms.hr.utils.allocate_earned_leaves` and the
`LeaveAllocation.validate/on_submit/create_leave_ledger_entry` code paths.
Resolve earned leave scheduler conflict for only Paid Leave. Validate an
isolated fractional credit in demo, including submit/cancel, allocation date
boundaries and the leave balance calculation. Establish historical cutover,
then introduce one-employee controlled posting with database locks, audit
references and explicit confirmation.

Regression test:
```python
import unittest
from marina_custom_apps.marina_leave_management import test_precision
suite = unittest.defaultTestLoader.loadTestsFromModule(test_precision)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print("PASS:", result.wasSuccessful(), "tests:", result.testsRun)
```
