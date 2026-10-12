# 月末备份清理

在用户已授权定期清理的环境中，每月最后一天北京时间 23:00 清理处理过程中生成的台账和照片备份。优先更新已有的“月底清理台账和照片备份”任务，不创建重复任务。本仓库不携带本机任务 ID 或自动创建定时任务；新环境需根据用户授权配置。普通录入、技能更新和测试不提前清理真实备份。

## 范围与执行

- 范围由 `assets/settings.json` 的 `backup_batch_root` 限定，示例为 `D:/DeliveryNotes/runtime`，实际路径只在本机配置。只扫描其直接子目录 `delivery-batch-YYYYMMDD-HHMMSS/backups` 中清单登记的文件。台账后缀为 xlsx/xls/xlsm；照片后缀为 jpg/jpeg/png/webp/tif/tiff/bmp/heic。
- 月末 23:00 起可清理截至运行时的已完成备份。其他时间仅补清理已经结束月份的备份，新月份备份保留。时间按 UTC+8 计算，与电脑显示时区无关。
- 默认预检：`scripts/cleanup-delivery-backups.ps1 -ReportPath <批次目录之外的新路径.json>`。实际清理使用另一个新报告路径并加 `-Execute`，脚本会重新核验。可传 `-SettingsPath`、`-PythonPath`；默认优先使用 Codex 内置 Python。
- `-AsOf 2026-10-31T23:00:00+08:00` 仅模拟预览日期，不能和 `-Execute` 同用。Python 辅助脚本只生成计划，没有删除能力。
- 执行前写完整预检清单，执行时逐文件写入并落盘 journal；使用 PowerShell `Remove-Item -LiteralPath` 逐个删除，不递归删除目录。每次生成新报告，不覆盖旧证据。重试时已不存在的备份记为 `already_absent`，不再计入删除数量。

## 清理条件及保留条件

批次完成、无待核/失败、保存核验完整、全部进度已清理，才可清理该批次。核验失败保留整批。未登记文件不删除；批次记录、清单、脚本、核验记录及清理日志不删除。正式台账、待处理单据、正式归档都不在删除范围。

每张已采用照片：自提核验运输及配送两处正式归档；厂发核验配送归档；归档哈希必须等于原照片登记哈希。备份自身也必须与登记哈希一致。备份目标及全部父目录禁止符号链接、目录联接、重解析路径和路径越界。核验正式归档时，允许已观察到的坚果云普通文件标签 `0x9000601A`，仍须完整读取并核验哈希；其他不明重解析对象保留。

正式台账只核验文件存在和历史保存核验记录，不能要求当前台账哈希等于历史哈希，因为后续批次会继续录入。执行前及逐文件删除前重新检查完成证据、归档和备份；中途变化停止该批次，记录原因并保留剩余文件。

## 批次证据格式

沿用已有字段，不改写历史业务记录。新批次按下列结构输出，缺证据时补做真实核验，不能为通过清理而直接改状态。

- `backup-manifest.json`：数组，每项包含绝对路径 `source`、`backup`，原始 `sha256`，带时区的 `time`。原单和将改的工作簿先备份并核验。备份目录之外的旧版本备份不在本清理范围。
- `progress.json`：逐单数组，含 `source_file`、`source_sha256`、完整 `note`、`status=cleaned`、`overview_rows`、归档 `settlement_target/settlement_sha256`；自提另含 `ledger_rows`、`primary_target/primary_sha256`。保留正常处理阶段记录。
- `completion.json`：`status=completed`、`notes_completed`、`source_cleaned`、`pending_in_folder=[]`、`pending_notes=[]`、`handles_released=true`。兼容已有无 status 但计数、进度、核验均完整的批次。
- 每个实际保存的工作簿输出 `<名称>-disk-verified.json`：`source` 为正式工作簿绝对路径，`ledger_sha256`、`disk_verified=true`。至少有配送台账核验；自提另有运输台账核验。保留实际保存方法等审计信息。

### 后续批次完成待核项

原完成记录用 `status=completed_after_confirmations`，保留本批原完成数量，新增 `remaining_notes_resolved` 和 `resolved_by_batch`；两者合计必须覆盖逐单进度。`resolution.json` 指向后续 `batch`，列出 `resolved_notes`。对应进度也记录 `resolved_by_batch`。脚本核查后续批次已完成、对应单号和归档证据一致；循环引用或缺证据保留。

### 用户保留旧版、放弃新版照片

备份项登记 `disposition=rejected_duplicate_photo_keep_existing_archives`、用户原话 `user_decision`、`decision_evidence`、`resolution_report`、`authoritative_archive_sha256` 和两处正式归档路径。进度用 `status=cleaned_duplicate_keep_existing` 及相同 disposition；归档哈希填写采用旧版的哈希。

确认文件保留 `user_message` 或 `user_decision`。处理结果必须含对应 `delivery_no`、`source_sha256`、同一 disposition、`review_status=same_physical_note_verified`、用户决定、旧版归档路径/哈希，以及 `cleanup_status=deleted_rejected_duplicate`。先核验未采用备份自己的哈希，再核验采用旧版归档的哈希，不要求两版本相同。跨批次重传导致原备份哈希不同的，原进度须有明确核实的 `reviewed_backup_sha256`。

## 检查和报告

`scripts/run-tests.ps1` 汇总所有回归检查；测试仅操作临时目录。真实批次验证只预览并保留报告。报告台账/照片各自删除数量、释放空间和保留原因。无可清理项且无异常时保持安静；完成清理、失败或需要用户处理时报告。不要将测试通过表述为绝对没有 bug。
