# Design Document: multiple files and controlled published revisions

## Why
Design teams may supply separate Tech Packs for the same collection/mood board. Use one **Design Document** containing multiple files; its **Selected Designs** table assigns the entire document and every attached file to each listed Design Code.

## Current release
- Existing **Primary File** continues to work as before.
- New **Additional Designer Files** child table: Designer/Contributor, File, Description. Every row becomes part of the same Design Document.
- Publication accepts a Primary File, Additional Designer Files, or both (at least one file required).
- Max 50 unique valid File URLs per Design Document; missing ERPNext File records cause validation error.
- Additional file rows cannot be changed after publication, including via API.
- Design Code -> Related Documents displays all files belonging to each linked Design Document.
- On saved form, temporary uploads by the current user attached to a temporary Design Document identifier are automatically reassociated with the saved document.
- **Replace Published File** is controlled by the distinct **Replace Published Document** action, plus Design Document Read, Create, Edit. Administrators have normal override.
- Replacing a published file creates a NEW **Published** Design Document, copying design assignments and every unchanged file. Only the selected file is replaced. Previous version and milestone evidence references remain intact.
- Superseded versions are excluded from new milestone evidence selections and Design Code linking, but remain accessible as historical records.
- No direct modification to previously published File URLs, completed milestone execution, or custody event evidence links.

## Demo UAT — mandatory before production deployment
1. Create Draft document with Primary File only; publish and verify selection/evidence.
2. Create Draft with two additional files (e.g. two designers), no Primary File; publish. Open each file from each linked Design Code.
3. Verify a broken/missing child File URL blocks publication; duplicate URLs block save.
4. Check legacy single-file documents still open unchanged.
5. Confirm non-authorized participants see NO Replace Published File button and cannot call its server endpoint.
6. Grant **Replace Published Document** action to a test participant who also holds Read/Create/Edit, verify action works only with an owned uploaded file and valid reason.
7. Replace Primary File or a selected Additional Designer File; verify a NEW Published Document ID is created, every unchanged file and design assignment copied, and old File records retained.
8. Confirm historical milestone execution/custody events still point to the OLD document. New milestone evidence lookup offers only latest version.
9. Attempt to edit/delete/relink a superseded record; verify all operations are blocked.
10. Verify no changes to unrelated ERPNext DocTypes, Company, native business permissions or production state.

**Deployment:** New DocType and parent table require Frappe Cloud migrate. GitHub CI is static/unit validation, not end-to-end Bench execution.
