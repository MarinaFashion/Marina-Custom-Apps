# Marina Design Management — clean consolidation into Marina Custom Apps

**Target**: Frappe/ERPNext v15, demo site `marinademo.frappe.cloud`.

**Status**: isolated integration branch, not approved for production deployment until demo verification. This guide deliberately does **not** preserve existing experimental Design Management documents.

## Architecture

| Before | After |
|---|---|
| Standalone site app `marina_design_management` | No standalone site app |
| Python root `marina_design_management` | `marina_custom_apps.design_management` |
| DocType/controller root `marina_design_management.marina_design_management` | `marina_custom_apps.marina_design_management` |
| Design assets `/assets/marina_design_management/...` | `/assets/marina_custom_apps/...` |
| Module Def `Marina Design Management` owned by standalone app | Module Def `Marina Design Management` owned by `marina_custom_apps` |
| Workspace `Marina Design Management` | Same independent workspace name |

Standard Design DocTypes retain their **names**, but old experimental records will be removed during standalone-app uninstallation. If any record must be retained, abort and redesign the migration. Other Marina Custom Apps DocTypes and data must never be deleted.

## Cutover order — demo ONLY

1. Capture a full Frappe Cloud demo backup/snapshot and verify the backup is recoverable. Record the two app branch heads and current installed-app list.
2. **Before deploying the integration branch**, uninstall `marina_design_management` from the **demo site only** (Frappe Cloud Site → Apps → Uninstall, if available; or authorized site console `bench --site marinademo.frappe.cloud uninstall-app marina_design_management --yes`). This deletes the old app's module DocTypes and records.
3. Confirm `marina_design_management` is **no longer installed on the demo site**, while `marina_custom_apps` remains installed. Do not uninstall `marina_custom_apps` or any finance/stock/POS app.
4. Point only demo's `marina_custom_apps` app to GitHub branch `integration/design-into-custom-apps-20261102`, deploy and run the normal Frappe migration/build. Do not install both implementations simultaneously under the same Module Def name.
5. During schema sync the combined app's `modules.txt` registers `Marina Design Management`; Frappe should synchronize the new module's standard DocTypes/pages/workspaces. The combined app's `after_migrate` sets up roles, references, milestone master, and finally independent workspaces.
6. Confirm `frappe.modules.utils.get_module_app("Marina Design Management") == "marina_custom_apps"`. Check the `Design Code`, `Mood Board`, `Design Cost Breakdown`, `Design Milestone Execution` and `Marina Discussion Message` DocTypes are present and belong to that module.
7. Clear browser cache and rebuild assets as appropriate for Frappe Cloud deploy. Old `/assets/marina_design_management/` URLs must no longer appear.
8. Validate standard Marina Custom Apps features **before** design testing: POS Reconciliation, Bank Statement Import, Stock Entry, DC Dispatch, Sales Forecasting and Purchase Order picker. Check any existing data counts are unchanged.
9. Validate Design Code creation, Mood Board / Drop, milestones and custody, production follow-up grid, published document evidence, design discussion and file download, Design Cost Breakdown approval/cancellation and new revision.
10. Log in as users with different roles; they must access only their allowed **top-level** workspaces. In particular POS Reconciliation must not depend on access to Marina Custom Apps, and Design Management must have its own allowed roles.
11. Confirm `Marina Custom Apps` landing workspace is hidden, and that all business workspaces have an empty `parent_page` in the DB after migration.
12. Only after passing demo UAT consider merging the integration branch to `main` and scheduling a separate production cutover.

## Important safety notes

- A GitHub repository merge is **not** an app uninstall or deployment. Do not treat a green static CI result as proof of live migration success.
- **Do not uninstall `marina_custom_apps`**. It owns operational stock, finance, POS, forecast and other records.
- `bench remove-app` and `bench uninstall-app` are different; do not run either on the production site as part of demo testing.
- Old standalone references, DocTypes and design demonstration data are intentionally discarded. New records are created after the consolidated app is installed.
- The original standalone repository should be archived **only after** the consolidated release is verified in demo and production; preserve its Git history.
- Any Frappe Cloud command needing write access must be performed through an authorized site administrator/deployment channel.

## Post-cutover diagnostic (Frappe console, read-only)

```python
import frappe
from frappe.modules.utils import get_module_app
print("Module owner:", get_module_app("Marina Design Management"))
print("Installed apps:", frappe.get_installed_apps())
print("Design Code:", frappe.db.exists("DocType", "Design Code"))
print("Cost Breakdown:", frappe.db.exists("DocType", "Design Cost Breakdown"))
for name in ("Marina Design Management", "POS Reconciliation", "Sales Forecasting", "DC Dispatch"):
    print(name, frappe.db.get_value("Workspace", name, ["parent_page","is_hidden"], as_dict=True))
```

**Expected**: `Module owner = marina_custom_apps`, no installed `marina_design_management`, both Design DocTypes present, listed module workspaces have `parent_page = ""` and `is_hidden = 0`. The old umbrella `Marina Custom Apps` workspace should have `is_hidden = 1`.
