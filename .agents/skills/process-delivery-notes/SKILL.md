---
name: process-delivery-notes
description: Process steel delivery notes from Nutstore. Enter self-pickup notes into transport ledgers, save images by project and carrier, copy images to the settlement archive by project and year, then sync transport data to the corresponding year's distribution ledger. Enter factory-direct notes directly into that year's distribution ledger and archive images. Resume from previous processing results; supports reconciliation, corrections and backup cleanup.
---

# Process Delivery Notes

## 每次开始与恢复：读取上次处理结果

1. 读取 [送货单业务逻辑规则](references/送货单业务逻辑规则.md) 全文；这是唯一业务规则及映射维护入口。运行 `scripts/rules_data.py --check` 确认派生映射一致，失败时先修复派生文件再继续。
2. 按 [状态工具接口](references/processing-state.md) 调用 `read-results`、逐页 `read-page`，读取磁盘保存的上次处理结果、全部未解决问题清单和本次单据的相关处理结果/专项决定。这里读取的是业务处理结果，不是聊天上下文，也不要求把全库历史证据重新装入上下文；具体证据按本次单据和待执行事项展开。
3. `begin` 取得 run；对照本次实际文件再继续。正式写入、归档和清理前 `guard`；每个验证阶段 `record`，中断也 `finish`。上下文压缩后按持久化结果和已读进度续做，版本未变时不从第一页重读。状态不明或目标文件变化先核文件。

## 两条处理路径

- **自提，依次执行：** 自提送货单 → 录入并保存对应运输台账 → 将送货单保存到文件1的对应项目/运输单位 → 将送货单从文件1同步到文件2的对应项目/年份 → 将已保存运输台账的数据同步到对应年份的配送台账，并验证保存。物流台账与运输台账指同一组文件；配送同步以运输台账为来源，并核对原单及采购/入库。恢复时先核实已完成步骤，只补未完成部分。
- **厂发，依次执行：** 厂发送货单 → 核对采购/入库，直接录入并保存对应年份的配送台账 → 将送货单保存到文件2的对应项目/年份。厂发不经过运输台账或文件1。

文件1是 `primary_archive_root` 的“送货单（自提）”文件夹，按项目和运输单位保存；文件2是 `settlement_archive_root` 的“配送台账及送货单(总)”文件夹，按项目和实际到货年份保存。路径取 `assets/settings.json`，不另建同义目录。配送台账也按已核实的到货年份选取，例如2026年用“副本2026-钢材配送台账.xlsx”；配置中的2026文件不是其他年份的默认目标。年份不明或对应台账不唯一时先核实，不凭单号日期推定。

图片同步完成与配送数据录入完成分别记录；自提文件1原图保留。两条路径均沿用完整规则的备份、查重、日期、数量、保存及源清理条件。用户仅要求修改技能时，只改技能并用测试副本验证，不处理业务文件。

待处理原单清理与未解决问题保留按完整规则R30a执行；配送台账入库的红色问题标注按R23a核对。单据专项暂缓决定从状态库读取。

## 按任务读取技术参考

|任务|技术参考|
|---|---|
|自提录运输、双目录保存及配送同步|[自提操作](references/workflow-rules.md)及[配送工具及列接口](references/distribution-workflow.md)|
|厂发直接录配送|[配送工具及列接口](references/distribution-workflow.md)|
|重传、版本、漏归档及恢复|[恢复工具](references/recovery-workflow.md)|
|保存及释放|[保存操作](references/save-close-workflow.md)|
|自提归档清单|[CSV字段](references/manifest-schema.md)|
|月底备份清理|[清理接口](references/backup-cleanup.md)，沿用现有任务；实际执行带-RunId|

业务规则已集中，参考文件仅维护工具接口与操作。项目/承运商映射由规则附表生成：`scripts/rules_data.py --check`。不能手改派生映射。

## 工具

- `scripts/delivery_state.py`：读取上次处理结果、按需展开证据、保留读取进度、阶段记录、问题状态及恢复。
- `scripts/inventory-pending.py --history-root <workspace> --report <batch>/inventory.json`；厂发加`--mode factory`。
- `scripts/distribution_checks.py --input <规范化快照.json> --report <计划.json>`：只生成检查计划。
- `scripts/archive-delivery-notes.ps1 -ManifestPath <csv> -ReportPath <新路径>`：自提双归档预检，通过后-Execute。
- `scripts/archive_factory_notes.py --manifest <json> --report <新路径>`：厂发预检，通过后--execute。
- `scripts/cleanup-delivery-backups.ps1 -ReportPath <新路径>`：清理预检；按规则正式执行加-Execute -RunId。
- `scripts/run-tests.ps1`：模拟数据回归及映射一致性。

## 报告

分别报告新增单/明细、更正、已存在、待核问题、磁盘保存、两处归档、源清理、释放及云同步的实际证据。维护阶段状态，不把照片归档当配送已录。技能更新/测试/历史导入不等于业务文件修改授权。
