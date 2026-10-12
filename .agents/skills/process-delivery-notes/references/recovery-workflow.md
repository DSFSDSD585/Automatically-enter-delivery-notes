# Recovery and blank-plate policy

The ledger scanning and dual-archive CSV commands below are for self-pickup notes. Factory notes use the distribution workflow's current-workbook readback and `archive_factory_notes.py`; they require a verified processing backup plus the project/year settlement copy, not a fabricated carrier archive. Both modes use the same full physical-note identity and no-duplicate rules.

User authorization: every blank vehicle/license plate is allowed for save and dual archive. Keep the field empty. Do not erase an existing reliable plate and do not waive missing delivery identity, project, arrival date, material quantities, or conflicting fields.

## Reconcile before writing

Run `scripts/reconcile-pending-delivery-notes.py --mapping <reviewed-ID-map.json> --history-dir <batch-record-dir> --report <inventory.json>`. The map uses `source_file`, `delivery_no`, and `source_sha256`. It links renamed reuploads by recorded hash, scans all four saved ledgers and archives read-only, and never authorizes deletion from number presence alone. Review its candidate states against actual photos before building a verified archive manifest.

1. Snapshot pending filename, SHA-256, size, and reviewed full business number. Link historical manifests by hash as well as filename. Hash difference alone proves neither a new physical note nor an error.
2. Scan all four ledgers read-only, finding the delivery-number header rather than assuming a column. Preserve complete numbers including leading zeros and suffixes. Record workbook absolute path/hash, worksheet, all material rows, and field values.
3. Resolve the two existing project directories. Classify: not entered, partially entered, saved/unarchived, primary-only, settlement-only, both archived/pending cleanup, complete/source absent, or conflict.
4. A saved record may recover directly from verified disk contents without starting Excel or its add-in. Use `save_method=existing` and a fresh `ledger_sha256`; this does not claim a save was performed now. Never trust mere presence of a number or placeholder row.
5. Validate material rows, dates, project, pieces, weight, remarks and full number against the reviewed image; blank plates are not blockers. Partial or contradictory records retain their sources and get a concrete question.
6. Check existing `-1`/`-2` records when a printed base number conflicts. The reconciler exposes these as `related_suffix_records` for review only. If the photo matches a previously saved suffix record in every required field, recover with that exact full number; do not add another ledger record or treat the base-number match as decisive.

## Idempotent archive

Use `archive-delivery-notes.ps1` after verification. Pass `source_sha256`, `ledger_sha256`, and `missing_fields` (only `vehicle`/`vehicle_plate`/`车牌`/`车牌号` allowed). Dry-run first. The script does no ledger editing.

The result CSV plus adjacent `.journal.jsonl` form the checkpoint trail. Two hashes are journaled before source deletion. Each completed/failed item is journaled immediately. Failed cleanup keeps both copies; a later run retries only missing steps. A missing source with recorded SHA-256 is complete only when both exact target copies match. Never hand-edit a hash to bypass a conflict.

## Rephotographed note / latest version

1. Compare old and new photos with the saved ledger. Confirm SAME physical note (not merely same printed number) and choose the latest user-designated photo. Do not infer the preferred version from filesystem timestamps alone.
2. If any business field conflicts, retain the source and ask or separately perform an authorized ledger correction. Do not replace archives before the saved record is consistent.
3. Use `replace-reviewed-archive-version.py` with explicit expected old hashes, pending hash, workbook hash, existing root paths, and written review evidence. It backs up each old version and verifies the backup before replacement. It never edits ledgers or deletes pending sources.
4. Then run the ordinary dual-archive preflight/execution, which rehashes all three images and the saved workbook before source cleanup.

Unknown project/number and ambiguous duplicate physical notes still require confirmation. PNG is authorized for native dual archiving; preserve its actual format and extension. Blank-plate authorization does not resolve identity conflicts.

Inspect PNG originals and match their full visible numbers against saved rows before reporting a status. The archive script now preserves PNG and checks its signature. If an exact number is absent, re-read the full-size number and compare contextual fields before declaring a numbering conflict; never silently remove a digit or leading zero. Pass the workspace as `--history-dir` to include direct results and carrier manifests/results in `batch-*` and `delivery-batch-*` directories, including those below `outputs`. Self-pickup discovery includes legacy loose images and the configured `自提` directory; factory images stay separate. History hits remain review candidates.

## Reporting

Report actual mutations separately from diagnosis: ledgers changed/saved, archive files created/reused/replaced with backups, verified physical-note pairs, sources removed, and source files remaining. List unresolved files with exact missing or conflicting fields. Never claim a batch is complete because the script ran or because both filenames exist.
