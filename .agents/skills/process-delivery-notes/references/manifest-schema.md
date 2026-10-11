# Batch manifest schema

Use one row per source image. Keep the same row through recognition, ledger entry, save confirmation, archiving, and retry.

## Required input fields

| Field | Required value before archive |
|---|---|
| `source_file` | Pending filename or absolute path inside the pending root |
| `delivery_no` | Exact complete business number read back from the saved ledger, including `-1`, `-2`, etc. when assigned to different physical notes that share a printed number |
| `carrier` | 顾氏、伟豪、享运或顺赢 |
| `project_alias` | Alias present in the project map or an exact directory match |
| `arrival_date` | `yyyy-MM-dd` |
| `ledger_file` | Saved transport-ledger filename |
| `ledger_sheet` | Target worksheet |
| `ledger_rows` | Written row or range, such as `93:95` |
| `recognition_status` | `verified` |
| `readback_status` | `verified` |
| `save_status` | `saved` |
| `ledger_saved` | `true` |
| `save_method` | `native`, `ui`, `offline`, or `existing` for fresh read-only verification of already-saved records |
| `saved_mtime` | ISO 8601 modification time captured after disk verification |
| `close_status` | `closed`, `failed`, or `not_attempted` |
| `close_method` | `native`, `ui`, or `none` |
| `close_error` | Blank when closed; concise reason when failed or not attempted |
| `ledger_sha256` | Fresh verified disk workbook hash; required for every entry, including native/UI/offline saves and existing records |
| `source_sha256` | Reviewed source hash; required for replay after source cleanup |
| `missing_fields` | Blank or vehicle/vehicle_plate/车牌/车牌号 only; blank plates are globally authorized |

`delivery_no` and `source_file` must each be unique within a batch. Text containing Unicode replacement code point `U+FFFD` is invalid.

`save_status=saved` and `ledger_saved=true` mean the written rows were reopened from the file on disk and matched the live read-back. A successful live command or UI click alone is not sufficient. `close_status=failed` is auditable but does not block archiving after the disk save is verified.

Before archive execution, verify that every detail row for the physical note has the same `delivery_no` and that the saved ledger cell equals it exactly. The primary filename core and the settlement filename core after removing the `MMdd已录` prefix must also equal `delivery_no`. Different physical notes with the same printed number require distinct ledger identifiers such as `<base>`, `<base>-1`, and `<base>-2`; multiple rows from one physical note do not.

## Script-managed output fields

- `primary_target`, `settlement_target`: resolved paired archive paths.
- `archive_status`: `Ready`, `AlreadyComplete`, `Completed`, or `Blocked`.
- `source_sha256`, `primary_sha256`, `settlement_sha256`: verification hashes.
- `error_reason`: blocking validation or execution error.
- `primary_status`, `settlement_status`: `pending`, `verified_existing`, or `copied`.
- `cleanup_status`: `pending`, `deleted`, or `already_absent`.

Use `-ReportPath` for every dry run and execution, distinct from the input manifest. The CSV and adjacent `.journal.jsonl` are the resumable audit trail; do not edit hash fields manually. `existing` requires a new photo-to-disk-row review and workbook hash, not a stale saved flag.

`offline`表示已授权的离线修改、保存及磁盘逐格核验；没有打开工作簿时close_status=not_attempted、close_method=none，close_error说明离线保存且句柄已释放，不伪造Excel已关闭。自提归档年份取arrival_date年份；已确认项目下允许创建缺失年份目录，不再退回项目根目录。厂发使用独立JSON归档脚本。
