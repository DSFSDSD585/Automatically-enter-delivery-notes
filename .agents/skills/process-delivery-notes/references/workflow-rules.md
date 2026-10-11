# Delivery-note workflow rules

## Configured locations

Read local `assets/settings.json` for the pending, ledger, primary archive and settlement archive roots. Copy `assets/settings.example.json` and fill in actual local paths before use. Local configuration and real business files are excluded from Git.

## Extraction and ledger rules

- Classify the carrier by delivery-number convention, not vehicle number.
- Blank vehicle plates are globally authorized for ledger save and archive; keep them blank. Other missing fields and contradictory information are not waived.
- Use the planned date printed or written in the delivery-note remarks.
- Use the delivery-note weight, not the warehouse slip or weighbridge value.
- Preserve a skipped delivery number by leaving a placeholder row containing that number.
- Before entering a printed number that already exists, compare the physical documents and their dates, vehicle, weights, pieces, and material details. If they are different delivery notes, keep the earliest existing record as the base number and assign the next distinct notes `<base>-1`, `<base>-2`, and so on. The assigned suffix is part of the ledger business number.
- If one physical delivery note contains multiple material detail lines, repeat exactly the same ledger number on all of its rows. Do not add `-1` or `-2` merely because the note uses multiple rows.
- Determine the next duplicate-note suffix by checking both the target worksheet and existing archives. Never reuse an already assigned suffix for a different physical note.
- Insert enough rows for all material lines and shift later numbers downward; never overwrite a later record.
- Before writing, read the destination range and stop if it contains an unrelated record.
- Fetch the live Excel tool schema before every write operation. Do not assume arguments accepted by an earlier session are still valid.
- In Office.js, copy with `destination.copyFrom(source, copyType)`. Do not use the unsupported `source.copyTo(destination)` pattern.
- Reuse adjacent formulas, borders, alignment, number formats, and unit prices only after checking that the neighboring record belongs to the same project and carrier.
- Treat a tool success response as provisional. Read the written range back and verify every field and formula before saving.
- Format newly entered cells as `宋体`, 11 pt.
- Record special handling such as `厂里退货` in the remarks column.
- Process multi-carrier batches one ledger at a time. Save, verify, and close the current ledger before opening the next ledger.
- Prefer a connected Excel save command. When none is advertised, use the controlled Excel UI fallback described in `save-close-workflow.md`; this is the user's standing authorization for target transport ledgers only.
- Save only after live read-back verification succeeds. Verify the file modification time and re-read the written rows from disk before marking the ledger saved. If writing, verification, or saving fails, do not archive or delete the pending image.
- After a verified save, close only the exact target workbook. A close failure must be reported but does not block paired archiving or pending-image cleanup when the saved file passed disk verification.
- Do not use COM, VBA/macros, Save As, overwrite prompts, or changes to Excel security settings as save/close fallbacks.
- Reject text containing Unicode replacement code point `U+FFFD` or evident mojibake before saving.
- Stop on read-only/occupied Nutstore workbooks and on duplicate delivery numbers found in different carrier ledgers.

## Project rules

- Use the explicit project map when names differ.
- If the same project directory exists under both archive roots, an exact-name match is allowed without a map row.
- If the settlement project has a `2026` subfolder, save there. Otherwise save in the settlement project root.
- Do not create a missing settlement project directory. Ask for the mapping first.
- A project map marked `pending` may contain a user-confirmed ledger worksheet but unresolved archive directories. This blocks automatic archiving, not authorized entry of clear fields into that confirmed worksheet. Never infer missing archive directories from the project name.
- Do not create a new mapping for `轻轨2标3工区`; the project is closed.

## Archive rules

- Treat the delivery number read back from the saved transport ledger as the authoritative business number, including a duplicate-note suffix such as `-1` or `-2`. The manifest `delivery_no`, primary archive filename, and settlement archive filename must use that exact complete number; never archive an image under a corrected, inferred, or different number.
- Before archive execution, compare the saved ledger cell with both proposed archive filename cores. Block the item if they differ.
- Primary filename: `<delivery_no>.jpg` for JPEG, `<delivery_no>.png` for original PNG.
- Primary directory: `<primary_root>\<archive_project>\<carrier>`.
- Settlement filename: `<arrival MMdd>已录<delivery_no>.jpg` or `.png`, matching the original image format.
- Settlement directory: the mapped project's `2026` subfolder when present, otherwise its root.
- Preflight both destinations before copying either file.
- Require both destination directories to exist before copying. Do not create a missing project or carrier directory during archive execution.
- Never silently overwrite. A reviewed replacement photograph of the SAME physical note uses the backup/verification procedure in `recovery-workflow.md`. For DIFFERENT physical notes with the same printed number, assign the numeric suffix in the ledger first; include that suffix in manifest `delivery_no` and both archive filenames. For multiple detail rows belonging to one physical note, retain one identical number across all rows and archive the note once.
- Delete the pending source only after source, primary copy, and settlement copy hashes agree.
- Persist each item's archive status, resolved targets, SHA-256 values, and error reason to the batch result CSV so interrupted batches can resume safely.
- Reconcile pending, saved ledgers and both archives before new entry; recover saved records independently of the live Excel connection. Journal both-copy verification before deletion, and final status immediately afterward. Keep successful copies when another step fails.

## Completion report

Report the number of ledger records, primary copies, settlement copies, skipped/conflicting documents, pending files remaining, and each workbook's save method, saved modification time, close method, close status, and close error.
