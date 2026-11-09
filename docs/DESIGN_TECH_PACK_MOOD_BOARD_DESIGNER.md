# Tech Pack architecture — Mood Board + Designer matching

This feature branch builds on the merged but **not yet demo-deployed** multi-file
Design Document implementation. Do not deploy directly to production.

## Business flow

1. Create a **Design Document** with **Document Type = Tech Pack**.
2. Select a **Tech Pack Mood Board** and its **Related Milestone Type**
   (use the exact milestone configured for Tech Pack release).
3. Add **Additional Designer Files**: one row for each Designer, each with
   her own attached Tech Pack. Designer and File are both mandatory.
4. Publish the Design Document. A published Tech Pack automatically links
   previously created Design Codes matching its Mood Board + Designer.
5. When a new Design Code is created with that Mood Board and Designer, it
   automatically links to the uniquely applicable Published Tech Pack.
   Designs receiving their first Designer after creation are covered too.
6. The Design Code's **Related Documents** shows only the matching designer's
   file—not every other designer's file on the same parent document.
7. Creating milestones revalidates the latest Published Doc, Mood Board,
   designer, milestone type and correct file. It stores both
   **evidence_document** and **evidence_file** in Execution and Custody Event.
   For Tech Pack Auto Completed workflows the link is resolved automatically.

All other Design Document types keep the prior explicit assignment process.
Historical Tech Packs published before this field existed can still be
read/linked by their old explicit assignment workflow.

## Security and evidence

- Drafts are never eligible; superseded versions are excluded from new
  evidence matching, but remain available for audit.
- The **Tech Pack Not Required** flag takes priority over automatic matching.
- A second active Tech Pack for the same Mood Board/Designer is rejected.
  A controlled published replacement supersedes the previous version.
- Only one file per Designer is accepted within a special Tech Pack.
- The published Mood Board, file contents and designer table are immutable.
- Historical milestone evidence remains pinned to its original Document ID
  and exact file URL. Returning a milestone clears the live evidence but keeps
  the old file reference in the immutable return event.
- Design Code reassignments do not silently rewrite old evidence; replacement
  versions copy only currently valid Design Code matches.
- Native Frappe access, Design User Permission, document publication action,
  and workflow/custody permissions remain in force.
- New Design Code linking is system-controlled and only materializes matches
  that satisfy the exact persisted Mood Board/Designer key.

## Demo UAT required

- [ ] Bench migrate installs Tech Pack Mood Board and evidence_file fields;
      existing documents and milestone records remain intact.
- [ ] Create Tech Pack with two designers under one Mood Board, using separate
      valid ERPNext File uploads. Publish succeeds.
- [ ] Two existing Design Codes assigned to different Designers automatically
      link to the SAME document but show only their own matching PDF.
- [ ] Create a new Design Code with the same Mood Board and Designer; its
      Related Documents includes that Tech Pack without manual selection.
- [ ] Create a Design Code without Designer and assign its first Designer later;
      automatic matching applies.
- [ ] Create a Design Code on another Mood Board or with an unmatched Designer;
      no file is linked.
- [ ] Design Code with Tech Pack Not Required is not auto-linked/required.
- [ ] Draft Tech Pack is never matched; unpublished or superseded documents do
      not appear as new evidence.
- [ ] Duplicate active Mood Board/Designer published Tech Pack is rejected.
- [ ] Create milestones and confirm exact evidence_file on Execution/Custody
      Event. Re-run bulk preview/create to compare the same eligibility.
- [ ] Return a milestone: current execution evidence is cleared; old events
      preserve both historical document and file.
- [ ] Publish a replacement for one designer's file. Old evidence and files
      remain unchanged; new matching selects the latest version.
- [ ] Verify old single-file legacy Tech Packs and Fitting/QC/Shipping
      Documents still work without a Mood Board.
- [ ] Verify no unrelated DocTypes or production site are changed.

## Scale and deployment notes

Matching is limited to 500 Design Codes per published Tech Pack and 500
candidate published Tech Packs. Queries are bounded and designer files use
batch lookups to avoid N+1 reads. Review these business limits if your
Mood Boards grow significantly beyond this size.

The branch requires Frappe Cloud migration. GitHub CI validates syntax,
DocType JSON and isolated matching invariants; only actual demo deployment
can validate uploaded File permissions and end-to-end milestone workflows.
