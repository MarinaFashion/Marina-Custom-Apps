# Tech Pack Not Required — per-design exception

Some repeat styles and ready-made samples do not need a standalone Tech Pack.

## Behavior
- On **Design Code** enable **Tech Pack Not Required** before creating the milestone plan.
- The exception applies **only** to a one-step **Auto / Completed** milestone with **Tech Pack**, **Technical Pack**, or **Techpack** as its configured Required Evidence Type.
- When Create Milestones runs, that Tech Pack milestone is recorded **Completed** without creating, publishing, or linking a fictitious Design Document. Its Custody Event action reads **Tech Pack Exempt - Auto Completed** and the evidence_document stays empty.
- Triggered successor milestones activate using their existing dependencies and custody rules.
- Other milestones, evidence types and approvals remain unchanged, including Fitting Report, QC Report and Shipping Document.
- The exemption cannot be toggled after creating a milestone plan. It cannot rewrite past evidence.
- Bulk creation uses the same exception.

## Demo QA
1. Make a new Design Code with eligible Designer, team assignments, main image, and Creation Date.
2. With the checkbox off, verify Create Milestones still requires a published linked Tech Pack for an Auto Completed Tech Pack step.
3. With the checkbox on, verify that only the configured Tech Pack milestone auto-completes without a document; subsequent milestone opens as configured.
4. Confirm no fake published document and no evidence_document, and check Custody Event action.
5. Confirm bulk preview and bulk create agree with single creation.
6. Confirm that other required evidence is never bypassed.
7. Confirm checkbox changes are rejected after plan creation and allowed before it.
8. Confirm existing plans remain unchanged after migration.

**Note:** The exception matches the configured *Evidence Type* rather than guessing from a milestone title. If the live master uses a different Tech Pack Evidence Type label, update the whitelist in the service deliberately after verifying that label.
