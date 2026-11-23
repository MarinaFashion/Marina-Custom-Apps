# Marina Leave Management — Phase 1 (read-only)

Branch: `feature/marina-leave-management`

## Scope
Pure accrual calculation and privileged preview endpoint. **No scheduler, hooks,
migration, Leave Allocation creation, ledger modification or background job.**

ERPNext / HRMS remains the source of truth. Preview is **not** a leave balance.

## Assumptions to validate with HR
- Annual 30: 30 / 330 normalized eligible days.
- Annual 21: 21 / 339 normalized eligible days.
- 30 standardized service units per full calendar month, prorated by actual
  calendar days for partial months or absences.
- Earned monthly credit appears on the next calendar month's first day.
- Join-date anniversaries define entitlement periods and annual caps.
- Only submitted **Approved** Paid Leave and Leave Without Pay exclude accrual.
- Overlapping absences count only once; half days are supported.
- Holiday exclusions in ERPNext applications may differ from calendar spans.
  Preview includes warnings for these cases; reconcile before posting.
- Paid Leave also reduces official HRMS balance; this simulator **only**
  estimates credits, and does not calculate historical ledger balances.
- Rejected applications and test allocation HR-LAL-2024-00001 are not used
  to produce entitlements; no test data is removed.
- Business decision remains open: guaranteed full entitlement at anniversary
  versus excluded leave periods and their effect on eligible service.

## Preview in demo console
```python
from marina_custom_apps.marina_leave_management.api import preview_employee
result = preview_employee("HR-EMP-00053", "2026-11-23")
print(result)
```

Endpoint requires an authenticated HR Manager / System Manager with Employee
and Leave Application read permissions. It may return historical dates and
leave-document identifiers; use only in authorized HR sessions.

## Tests
```bash
python -m unittest marina_custom_apps.marina_leave_management.test_accrual
```

## Next acceptance gate
Check leave-day handling (holiday lists and half-days), contract anniversary,
rounding in HRMS allocation, active employee status and historical cutover.
Do not enable any posting until HR validates sample calculations.
