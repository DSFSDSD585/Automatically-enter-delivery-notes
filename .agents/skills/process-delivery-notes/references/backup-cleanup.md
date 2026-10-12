# 月末备份清理工具接口

业务规则唯一来源：[送货单业务逻辑规则](送货单业务逻辑规则.md)。每次执行先按[状态工具接口](processing-state.md)实际读取规则和共享状态。

实际清理执行额外传 `-RunId <当前已完整读取规则及状态的run>`；settings.state_root指向共享状态，预检及删除前检查相关未解决问题。月底时间和范围见规则R32–R34。

预检：`scripts/cleanup-delivery-backups.ps1 -ReportPath <批次目录之外的新报告.json>`。执行使用另一个新ReportPath，加`-Execute -RunId <run>`。可选`-SettingsPath`及`-PythonPath`。`-AsOf 2026-10-31T23:00:00+08:00`仅用于模拟预览，不能与Execute同用。Python辅助脚本没有删除能力。每次报告路径唯一；相邻journal和result文件不得覆盖旧证据。

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
