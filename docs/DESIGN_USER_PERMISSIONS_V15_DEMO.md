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


## Design Team Role Link reference (demo regression fix)

For **Design Team Assignment.module_role**, native Frappe Link search needs
`Design Module Role` Read/Select access in addition to the individual
`Assign Team Tasks` / `Reassign Team Tasks` action. This is **reference
visibility**, not permission to create or modify role definitions.

- The `Design User Permission` document whitelist now accepts `Design Module Role`.
- `Marina Design Participant` has native Read/Select on the Role master;
  Create/Write/Delete remain **zero** for non-administrators.
- For users with enabled individual profiles, the `Design Module Role` row
  must have **Read=1, Create=0, Edit=0, Delete=0**. Absence of the row denies
  access. Other users retain the existing legacy module permission behavior.
- Previously saved profiles (such as Catherine) were created before this
  reference was in the table and need the Read row appended once after deploy.
- **Do not** give users `Manage Role Permissions` or native `System Manager`
  to fix team selectors.
- Confirm the Frappe DocPerm fixture is synced by migration. If a site has a
  `Custom DocPerm` override for `Design Module Role`, inspect it first; a
  custom override may supersede standard JSON permissions.

Demo verification:

```python
user = "catherine@marinafashion.com.sa"
print(frappe.has_permission("Design Module Role", "read", user=user))
print(frappe.has_permission("Design Module Role", "select", user=user))
from marina_custom_apps.design_management.security.user_permissions import document_allowed
print(document_allowed("Design Module Role", "read", user))
```

Expected after granting the individual Read row: three `True` values.
Test role dropdown, selecting an eligible employee, and saving the Design Code
(including the required reassignment reason) as Catherine.

## Permission editor and navigation cleanup (November 2026)

After deploying this branch and running `bench migrate` on **demo**:

- **Insert All Documents & Actions** is visible to System Managers on new and saved individual permission forms. It inserts only missing rows from the server-side catalog, retaining any existing grants or selections.
- All new document rows are unchecked. All new action rows are **Not Allowed**. Clicking the button does **not save** and does **not grant access**.
- On Save, any document row with all four permissions unchecked and any action row set to Not Allowed is **removed** from the saved profile. Missing entries are **denied** for enabled individual profiles. Repeat Insert All whenever you need to configure a previously omitted entry.
- Saving a profile with zero granted permissions is allowed (enabled profile still denies all).
- The workspace has independent shortcuts for **Design Module Role**, **Design Management Settings**, **Design User Permission**.
- The obsolete **Security & Permissions** and **Role Hierarchy** pages and their workspace shortcuts are removed, including cleanup of existing Page database records by a targeted idempotent post-model-sync patch.
- The Design Module Role DocType, its business hierarchy fields, active user memberships, and custody history **remain**; do not delete them.
- The **Design Workspace Visibility** matrix remains in Settings. Its list of configurable workspace items now uses the three active destinations, not obsolete page names; existing user/item rows are preserved, including historical values for removed pages.
- This change **does not** migrate other users or remove legacy authorization fallback. Do not deploy it to production until user permissions and workflow validation are complete.

UAT checklist:
- [ ] Open a saved profile; Insert All preserves current grants and inserts missing entries.
- [ ] Save and reload; unchecked documents and Not Allowed actions have disappeared from stored rows.
- [ ] Repeat Insert All; missing entries appear unchecked / Not Allowed again.
- [ ] Confirm saved Catherine grants remain unchanged after editing.
- [ ] Confirm all three new workspace links are present for authorized admin users.
- [ ] Confirm old security/hierarchy pages and shortcuts are gone after migration.
- [ ] Confirm Design Workspace Visibility matrix still loads and previously saved overrides remain.
- [ ] Confirm team assignments and milestone custody are unaffected.

## Matrix UI and participant selection

- Documents and Actions are displayed as compact scrollable matrices with sticky
  headings (similar to the existing Design Workspace Visibility matrix).
- The old child tables remain the authoritative **stored data**, but are hidden
  from the form; changes are written to the child rows through Frappe model
  updates. Matrix edits require form write/create rights.
- Documents: Read, Create, Edit, Delete checkboxes.
- Actions: mutually exclusive Not Allowed / Allowed / Custody Only radio choices;
  Custody Only is disabled except on **Advance Milestone Step**.
- Insert All adds only missing catalog entries with no grants; existing grants
  remain unchanged. Save discards unchecked documents / Not Allowed actions.
- The User picker uses the shared participant-user Link query: only enabled
  ERPNext System Users carrying the native **Marina Design Participant** role.
- Server-side validation repeats that eligibility test on save, so manual
  selections, imports and API writes cannot bypass the participant requirement.
- User role membership is independent of business role hierarchy and remains
  part of team assignment validation.

UAT: Test new and saved profiles; verify repeated Insert All, checkbox/radio
interactions, Save and reload, role-filtered user search and invalid user
rejection. Check no other Settings or Workspace Visibility changes.

## Unlinked Draft Design Document cleanup (Nov 2026)

A Draft Design Document with **zero Design Code assignments** and **zero milestone
evidence references** may have its attachment changed or cleared before publication.
Once published or linked, the original file remains immutable. Frappe may also remove File attachments associated with a deleted document.

To delete a Draft document, a Design participant with an enabled individual
profile must have **Design Document: Delete = checked** and **Edit = checked**.
The controlled **Document > Delete Unlinked Draft** form action also requires
that the user created the document (or is a System Manager), and checks every
condition again under a row lock. This lets authorized owners delete a working
Draft even when the participant's native ERPNext role has no general Delete
DocPerm; it does not grant a general delete capability for Published/linked
documents. Users with no individual profile retain legacy and native permission
checks. The existing on_trash checks still independently guard unpublished,
unlinked documents against deletion when referenced by evidence.

Demo UAT:
- [ ] Catherine with Edit but without Delete sees no Delete Unlinked Draft action.
- [ ] After administrator checks **Design Document Delete** for Catherine,
      she can delete her own unlinked Draft, but not anyone else's document.
- [ ] Unpublished, unlinked Draft supports replacing or clearing the attachment,
      followed by Save and subsequent Publish with an existing valid File.
- [ ] Linked Draft refuses attachment replacement and deletion.
- [ ] Published document refuses attachment replacement and deletion.
- [ ] Draft referenced by milestone execution/custody evidence refuses attachment
      replacement and deletion, regardless of current assignment table.
- [ ] Check no Design Code/milestone links or evidence rows were mutated.
