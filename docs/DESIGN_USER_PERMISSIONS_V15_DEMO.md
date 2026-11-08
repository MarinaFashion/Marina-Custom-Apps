# Marina Design User Permissions — demo validation

Branch: `design-user-permissions-v15`  
Status: **Candidate for isolated demo testing, NOT production approved.**  
Base: v15 `main` commit `9f7c091078ff17c5de16b6c246f8567a0d23a294`.  
Do not enable an individual profile for a production user before demo signoff.

## Simple design

One `Design User Permission` record per user, with two editable child tables:

1. **Documents** — Read, Create, Edit, Delete.
2. **Actions** — Not Allowed / Allowed / Custody Only. *Custody Only currently applies to Advance Milestone Step*, using the current execution's `current_custodian`, not the target step's role.

This is opt-in per user using `Enable Individual Permissions`. A new record starts disabled and contains all installed operational DocTypes and supported actions with **no grants**. Users without enabled profiles retain the legacy role system unchanged, including existing module RBAC enable/disable behavior.

Organizational roles remain required to identify eligible milestone assignees and validate that next custody is assigned to an enabled `Marina Design Participant`. They do **not** control action authorization or hierarchy scope for a user with an enabled individual profile. Business integrity rules remain (milestone sequence, evidence, valid user, immutable approved costings, etc.).

Native Frappe DocPerm remains a separate **maximum**: a user-level Allow cannot grant a right absent in the user's technical Frappe permissions. Use the admin-only **View Effective Permissions** to see document rights including the native gate.

## Deployment

1. In Frappe Cloud select **demo site only** (`marinademo.frappe.cloud`). Switch `marina_custom_apps` to branch `design-user-permissions-v15`, *not* `version-16`.
2. Build, deploy and run migration. Verify migration success at 100% and that **Design User Permission**, **Design User Doc Permission**, **Design User Action Permission** exist, with no missing schema/errors.
3. Log in as Administrator/System Manager on demo and open `/app/design-user-permission`.
4. Create a new record, select Catherine's **actual demo User ID**, leave `Enable Individual Permissions` disabled, and **Save**. The two matrices are prefilled with all supported entries, initially denied.
5. Click **Presets → Fill Operational Test Access**, inspect Documents and Actions, make any corrections, then enable individual permissions and **Save**.
6. Click **View Effective Permissions**. A native `False` cannot be overruled by an individual Allow, and must be resolved separately with Design-only native privileges.
7. Log out and log in as Catherine; test on non-critical demo designs.

## Acceptance test matrix

- [ ] Profile absent/disabled: compare existing user behavior before/after upgrade — **must be unchanged**.
- [ ] Profile enabled, all rights denied: Mood Board / Design Code / Design Document read, create and write blocked.
- [ ] Document rights: grant Read/Create/Edit separately; deny Delete; verify List, Form, normal REST API, and direct whitelisted endpoints.
- [ ] Team: Assign Team Tasks and Reassign Team Tasks Allowed; select users from Designer, Merchandiser, Technical Fitting, QC, Shipping; user must be valid active role member.
- [ ] Team: Not Allowed prevents UI and server-side assignments.
- [ ] Milestones: Assign Milestones Allowed creates a plan with valid designer, image and creation date.
- [ ] Milestones: Advance Milestone Step Allowed works when a valid transition and required evidence are supplied, regardless of hierarchy.
- [ ] Milestones: Custody Only permits **the current custodian**, denies another user even if they are a Head; validates against `Design Milestone Execution.current_custodian`.
- [ ] Milestones: Not Allowed denies direct API calls; milestone sequence and evidence are still enforced even under Allowed.
- [ ] Documents: Publish Document and Remove Published Assignment Allowed/Not Allowed both checked; note these are separate actions.
- [ ] Chat: Send Discussion Message Allowed and Upload Discussion Attachment Allowed; each independent and checked on the server; parent Design Code/Mood Board Read still required.
- [ ] Financial: Cost Breakdown Create/Edit/Approve permissions independent; final approval state and commercial document protections unchanged.
- [ ] Other design actions: Create ERPNext Items, Return to Milestone, Delete Design Code, Clear Related Milestones have independent action gates.
- [ ] Permissions: Administrator/System Manager can edit user matrix. Ordinary staff cannot configure other users. No new Finance/Stock/HR role granted.
- [ ] Multi-user: test a second **unconfigured** user to ensure no regression.
- [ ] Performance: test Follow-Up Grid and team user selector with at least 100 designs; check server timings and query counts against v15 baseline.

## Limitations / follow-ups before production signoff

- Static source checks and unit contract tests are included, **but no Frappe v15 bench migration or browser end-to-end test has been run from ChatGPT**.
- Not every historically available Design UI button has a dedicated workflow action. Standard Create/Edit/Delete are controlled by document permissions; existing server methods for special commands require further acceptance testing.
- A configured user's Document Allowed applies to all records of that DocType subject to native permission, Frappe User Permission restrictions, and non-negotiable workflow validation. There is no separate Assigned/Own document scope in this first release.
- **Custody Only** is implemented for milestone advancement, not as a general record-level custody mode for create or chat.
- The profile does not change users' global ERPNext roles or the module RBAC master switch. An enabled user profile takes precedence for supported Design operations.
- Production remains untouched. Merge into main only after demo signoff, resolving any failures revealed by acceptance tests.

## Rollback on demo

First disable each `Design User Permission.enabled` profile and save. This restores legacy authorization without removing records. For complete rollback, revert demo application code to its preceding v15 deployment after taking a database snapshot. Do **not** delete Data Definition records manually while custom Python handlers are still installed.

## Technical validation commands

Run from branch checkout:

```bash
python -m compileall -q marina_custom_apps
python -m unittest discover -s tests -p test_design_user_permissions_unit.py -v
```

From demo bench console:

```python
import frappe
for doctype in ("Design User Permission", "Design User Doc Permission", "Design User Action Permission"):
    print(doctype, bool(frappe.db.exists("DocType", doctype)), frappe.db.table_exists(doctype))
```

## Simplified Settings UI (phase 1)

The old module-level RBAC checkbox and the two permission child tables on `Design Module Role` are now **hidden, not deleted**. The old database rows remain available to the legacy fallback for any user with no enabled individual permission profile. Existing records and application validation are preserved; do not manually remove legacy tables yet.

- `Design Management Settings`: retained **Design Workspace Visibility**, Mood Board Base Team, Item field mappings, retention settings, and **Design Team Membership** (Module User Roles).
- Added **Manage Design User Permissions** shortcut within Settings.
- `Design Module Role`: retains organizational attributes, reporting and group; legacy DocType and Action permission tables are hidden.
- The old global `module_rbac_enabled` configuration remains stored and unchanged. It is not a new permission source for users with an enabled individual profile.
- Added explicit DocType controller overrides for three `Design User Permission*` DocTypes to avoid the stale standalone module map when opening a **new** console or browser session. Existing other module DocTypes are unchanged.

**This is a UI cleanup, not a removal of legacy authorization code or a data migration.** It is not safe to delete the old system until all active users are configured and audited in Design User Permission; doing so would otherwise change access for the unconfigured users.

### Additional demo checks for cleanup

- [ ] Existing Catherine profile and 13/14 configured rows still load after new deployment.
- [ ] Open a **fresh** `bench --site marinademo.frappe.cloud console` and `frappe.get_doc("Design User Permission", "catherine@marinafashion.com.sa")` without rebuilding the module map manually.
- [ ] Design Management Settings displays the original Workspace Visibility matrix unchanged and retains all saved user/item visibility overrides.
- [ ] Design Team Membership remains editable and organizational roles still determine eligible assignees and custody.
- [ ] Design Module Role no longer shows role-based Document/Action grids.
- [ ] The new Settings button opens `Design User Permission`.
- [ ] Staff without enabled individual profiles retain legacy permissions; confirm with at least one user.
- [ ] No changes to `marina.frappe.cloud` production.

