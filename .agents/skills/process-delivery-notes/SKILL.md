---
name: process-delivery-notes
description: Process steel delivery notes from Nutstore, enter self-pickup transport ledgers or factory-direct notes, synchronize transport records to the 2026 distribution ledger without duplicates, reconcile purchase and inbound records, verify saves, and archive originals by project and year. Use for delivery batches, backfills, corrections, reconciliation, interrupted processing, and monthly cleanup of processing backups.
---

# Process Delivery Notes

## 每次开始与恢复：必须实际读取

1. 读取 [送货单业务逻辑规则](references/送货单业务逻辑规则.md) 全文；这是唯一业务规则及映射维护入口。运行 `scripts/rules_data.py --check` 确认派生映射一致，失败时先修复派生文件再继续。
2. 按 [状态工具接口](references/processing-state.md) 调用 read-context、逐页 read-page，读取最新实际处理、全部未解决问题及本次单据专项历史。不能只看摘要；被截断的输出必须重读。
3. begin取得run；对照本次实际文件再继续。正式写入、归档和清理前guard；每个验证阶段record，中断也finish。状态不明先核文件。

## 按任务读取技术参考

|任务|技术参考|
|---|---|
|自提新单|[运输操作](references/workflow-rules.md)，运输保存核验后接配送同步|
|厂发新单、历史运输同步配送|[配送工具及列接口](references/distribution-workflow.md)|
|重传、版本、漏归档及恢复|[恢复工具](references/recovery-workflow.md)|
|保存及释放|[保存操作](references/save-close-workflow.md)|
|自提归档清单|[CSV字段](references/manifest-schema.md)|
|月底备份清理|[清理接口](references/backup-cleanup.md)，沿用现有任务；实际执行带-RunId|

业务规则已集中，参考文件仅维护工具接口与操作。项目/承运商映射由规则附表生成：`scripts/rules_data.py --check`。不能手改派生映射。

## 工具

- `scripts/delivery_state.py`：启动真实读取、阶段记录、问题状态、恢复及可阅读报告。
- `scripts/inventory-pending.py --history-root <workspace> --report <batch>/inventory.json`；厂发加`--mode factory`。
- `scripts/distribution_checks.py --input <规范化快照.json> --report <计划.json>`：只生成检查计划。
- `scripts/archive-delivery-notes.ps1 -ManifestPath <csv> -ReportPath <新路径>`：自提双归档预检，通过后-Execute。
- `scripts/archive_factory_notes.py --manifest <json> --report <新路径>`：厂发预检，通过后--execute。
- `scripts/cleanup-delivery-backups.ps1 -ReportPath <新路径>`：清理预检；按规则正式执行加-Execute -RunId。
- `scripts/run-tests.ps1`：模拟数据回归及映射一致性。

## 报告

分别报告新增单/明细、更正、已存在、待核问题、磁盘保存、两处归档、源清理、释放及云同步的实际证据。维护阶段状态，不把照片归档当配送已录。技能更新/测试/历史导入不等于业务文件修改授权。
