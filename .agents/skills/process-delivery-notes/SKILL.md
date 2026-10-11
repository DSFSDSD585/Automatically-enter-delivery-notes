---
name: process-delivery-notes
description: Process photographed steel delivery notes from the Nutstore pending folder through carrier and project resolution, live Microsoft Excel ledger entry, verification, save, dual archiving to the processed-delivery and settlement directories, SHA-256 validation, and safe pending-file cleanup. Use for new delivery-note batches, skipped-number backfills, carrier-rule updates, project-alias maintenance, or auditing delivery-note processing results.
---

# Process Delivery Notes

Process each clear delivery note as one resumable transaction: identify it, preflight the ledger destination, write and read it back, confirm the workbook is saved, then create and validate both archive copies before removing the pending source.

## Required resources

- Read [references/workflow-rules.md](references/workflow-rules.md) before processing a batch.
- Read [references/project-map.csv](references/project-map.csv) when project names differ across the ledger, processed archive, and settlement archive.
- Read [references/carrier-rules.json](references/carrier-rules.json) when classifying or changing carrier rules.
- Read [references/manifest-schema.md](references/manifest-schema.md) before creating or resuming a batch manifest.
- Read [references/save-close-workflow.md](references/save-close-workflow.md) whenever a ledger will be saved or closed automatically.
- Use [assets/batch-manifest-template.csv](assets/batch-manifest-template.csv) to prepare the verified batch.
- Use [scripts/archive-delivery-notes.ps1](scripts/archive-delivery-notes.ps1) only after every listed ledger is saved.
- Read [references/recovery-workflow.md](references/recovery-workflow.md) when pending contains previously entered/archived notes, reuploads, or version conflicts.
- Use `scripts/inventory-pending.py --history-root <workspace> --report <new-batch>/inventory.json` for a new stable inventory. Do not overwrite the original inventory after cleanup; a new reconciliation report must retain original source hashes/indexes used by operation plans.

## Workflow

1. Inventory pending images by SHA-256 and reconcile saved ledgers plus both archives BEFORE new entry. Resume saved-but-unarchived and archived-but-not-cleaned notes first. Inspect every image and extract delivery number, project, planned date, arrival date, vehicle, material lines, delivery-note weight, pieces, and remarks. Blank vehicle plates are globally allowed: preserve blanks, never guess, and do not block saving or archiving solely for that reason. Other missing identity/date/material fields still require partial-entry or confirmation.
2. Resolve the carrier from the numbering rules, never from the vehicle. Search all four ledgers when a rule does not resolve uniquely.
3. Resolve the project through the project map. Do not guess similar project names or create a missing settlement project folder.
4. Use the live Microsoft Excel workflow for ledger edits. Confirm the workbook is editable, preserve skipped-number placeholder rows, and distinguish duplicate physical notes from multiple detail lines. If different physical delivery notes carry the same printed number, keep the first as the base number and assign later notes `-1`, `-2`, and so on in the ledger. If one physical note has multiple material detail lines, repeat the same ledger number on every detail line without adding a suffix. Insert enough rows for all material lines and format new cells as Songti 11 pt. Before every write, fetch the current tool schema and use its exact parameter names. In Office.js, copy formulas or styling with `destination.copyFrom(source, copyType)`; never call `source.copyTo(destination)`. Read the destination before writing and stop if it contains an unrelated record.
5. Treat a successful write response as provisional. Read the written range back and verify identifiers, dates, weight, pieces, formulas, remarks, row order, duplicate numbers, and text encoding. Set `readback_status=verified` only when the actual cells match; otherwise retry using the current schema or leave the item blocked.
6. Save only after read-back verification. Group the batch by ledger and finish one workbook before opening the next. Prefer an advertised connected Excel save command; when none exists, use the narrowly scoped UI fallback in the save/close reference. Verify the on-disk modification time and re-read the target rows from the saved file before setting `save_status=saved` and `ledger_saved=true`.
7. After disk save verification, close only the exact target workbook. Prefer an advertised connected close command; otherwise use the same controlled UI fallback. A close failure does not invalidate a verified save and does not block archiving, but it must be recorded and reported. Never use COM, macros, or changes to Excel security settings.
8. Run the archive script without `-Execute`. Resolve every blocked item before continuing.
9. Run the same command with `-Execute`. The script must verify both copies by SHA-256 before deleting the pending source.
10. Persist per-step journal events before cleanup and after each note, plus the final result CSV. Report separately new copies, reused copies, verified pairs, deleted sources, skipped/conflicting items and pending count. A resumed note may need only one new copy; compare verified paired-note totals, not new-copy counts.

Current user overrides: archive PNG in its original format with `.png` in both destinations; never convert or merely rename bytes. Checked new material rows use Songti 11 pt black text. Inventory history must include all carrier-specific `*-result.csv` and `*-manifest.csv` files under prior `batch-*` directories, not only `archive-result.csv`. Historical matches are candidates requiring fresh disk and archive verification, never automatic deletion authority.

## Archive commands

Dry run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/archive-delivery-notes.ps1 -ManifestPath <batch.csv> -ReportPath <batch-result.csv>
```

Execute after reviewing the dry run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/archive-delivery-notes.ps1 -ManifestPath <batch.csv> -ReportPath <batch-result.csv> -Execute
```

Never silently overwrite an existing file. Treat an identical hash as already archived. A confirmed newer photograph of the SAME physical note follows the reviewed version-backup/replacement path; do not assign a business suffix just because image bytes differ. A business suffix assigned to distinguish DIFFERENT physical notes is part of the ledger number and must appear identically in both archive destinations. A single note's multiple material rows must retain one identical number.
