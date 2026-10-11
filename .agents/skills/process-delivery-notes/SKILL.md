---
name: process-delivery-notes
description: Process steel delivery notes from Nutstore, enter self-pickup transport ledgers or factory-direct notes, synchronize transport records to the 2026 distribution ledger without duplicates, reconcile purchase and inbound records, verify saves, and archive originals by project and year. Use for delivery batches, backfills, corrections, reconciliation, and interrupted processing.
---

# Process Delivery Notes

按单据类型选择流程；以保存后重新读取的实际内容为完成依据。先备份，先查重，逐项留存进度，重试只补未完成步骤。技能更新或测试不等于授权处理正式业务文件。

## 流程入口

| 请求 | 必读及范围 |
|---|---|
| 自提新单 | [运输规则](references/workflow-rules.md)、[项目映射](references/project-map.csv)、[承运商规则](references/carrier-rules.json)。运输台账保存核验后接配送同步。 |
| 厂发新单 | [配送录入及同步](references/distribution-workflow.md)。直接匹配入库并录总览，不虚构运输台账或承运商。 |
| 已有运输记录同步配送 | [配送录入及同步](references/distribution-workflow.md)。按用户年份/范围；全部2026年包括四本运输台账及旧配送账中的2026记录核查。 |
| 重传、漏归档、重复、更正 | [恢复规则](references/recovery-workflow.md)及对应入口。冲突项待核实，不重复补录。 |

所有保存操作读取 [保存与释放文件](references/save-close-workflow.md)。自提双归档读取 [CSV清单](references/manifest-schema.md)；厂发使用配送参考中的JSON清单。

## 共用约束

1. 每批修改前备份将改的工作簿及待处理原单，记录路径、时间、SHA-256并核验；使用独立批次目录，不能覆盖前次备份。
2. 完整保留编号前导零、位数及后缀。同一物理单多材料/多入库编号共用编号；不同物理单确实重号才分配`-1/-2`。不同图片哈希不等于新单。不得全局替换O/0、I/1或删零。
3. 项目和销售公司用已核实对应关系，不靠相似名字/同重量推断。厂发销售简称与自提承运商规则分开。
4. 保持原行高、列宽、隐藏状态、公式、格式及已有备注；不全表自动适应。必要新行继承适合模板，不改变原行。运输新材料行宋体11磅黑字；更正值红字、本行追加修改内容，不写更正来源。原红底保留可读文字，备注标红。
5. 写前重读原值并比较文件哈希，若用户/同步客户端已改文件，重新核对。写后核验关联计算，保存后从磁盘重读。命令成功或修改时间变化不等于完成。
6. 原图按实际到货年份存对应项目。自提运输和配送双归档；厂发配送归档加处理前备份。缺项目映射先核实；已确认项目下缺年份目录可以创建，不能退回项目根目录。
7. 记录`recognized → matched → written → disk_verified → archived → cleaned`及每步行号/哈希。重试仅补缺步骤。同步历史运输记录不删除或搬动原归档。
8. 空车牌允许，其他缺日期/身份/数量字段仍待核；用户说待核实的保持待核。退货、取消、合计和占位号不算新配送。

## 工具及边界

- `scripts/inventory-pending.py --history-root <workspace> --report <new-batch>/inventory.json`：自提稳定清单；厂发加`--mode factory`。历史命中只是候选。
- `scripts/distribution_checks.py --input <reviewed-snapshot.json> --report <new-plan.json>`：已规范化原单/运输、入库、已有配送的去重、分配、数量及磅差检查。只输出计划，不识图、不写台账、不替代采购复核。格式见配送参考。
- `scripts/archive-delivery-notes.ps1 -ManifestPath <batch.csv> -ReportPath <new-result.csv>`：自提双归档预检，通过后加`-Execute`。提供当前磁盘工作簿哈希。
- `scripts/archive_factory_notes.py --manifest <factory.json> --report <new-result.json>`：厂发归档预检，通过后加`--execute`，核验保存后的配送实际行。

逐工作簿完成写入、保存、磁盘核验和释放。图片同名异内容不覆盖。自提版本替换见恢复参考；厂发保留冲突文件，不靠变编号规避。

## 完成报告

分别报告新增单/明细行、已存在跳过、更正、待核实、备份、实际保存工作簿、归档新增/复用、源清理和释放情况。无直接云端或坚果云状态证据时只确认本地保存，不声称上传成功。
