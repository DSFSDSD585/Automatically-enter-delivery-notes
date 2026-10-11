# Automatically enter delivery Notes

钢材送货单处理技能，覆盖自提运输台账、厂发直接录入配送台账，以及四本运输台账向2026配送台账同步。

流程入口为 [.agents/skills/process-delivery-notes/SKILL.md](.agents/skills/process-delivery-notes/SKILL.md)，简要功能见 [功能说明.txt](功能说明.txt)。图片识别、采购证据核对和工作簿写入由Codex配合可用工具完成；脚本提供只读匹配检查及归档，不是独立的一键OCR应用。

## 本次迭代

- 厂发编号中的销售公司与自提承运商分别识别，厂发直接匹配入库信息，不生成虚构运输记录。
- 运输同步先核对完整单号、同组明细合计及旧台账记录；多入库编号按剩余件数分配，整批共享余额。
- 计划日期严格一致，螺纹重量差异复核采购；盘材暂估采购量与项目实收磅差分开判断。
- 备份、保留行高列宽和公式、更正标红备注、入库状态填色、保存回读及释放文件纳入共用规范。
- 归档按实际到货年份；所有保存方式都要求当前文件哈希，支持已授权的离线保存和中断恢复。

## 配置

Windows、PowerShell、Python 3.11或以上。只读旧Excel扫描依赖`openpyxl`；新分配和厂发归档脚本使用Python标准库。实际工作簿写入需可用的Excel连接或表格文件工具。

1. `python -m pip install -r requirements.txt`
2. 将技能内`assets/settings.example.json`复制为`assets/settings.json`，填写本机路径。已有配置需补充`factory_pending_root`、`distribution_ledger`和`procurement_root`。
3. 将`references/project-map.example.csv`复制为`references/project-map.csv`，填写已确认映射；真实映射只留本地。
4. 在Codex中使用`$process-delivery-notes`，明确厂发/自提/历史同步范围。批次报告保存在本地`runtime/batch-YYYYMMDD`，先创建该目录。

## 入口命令

```powershell
$skill = '.agents/skills/process-delivery-notes'
# 只读盘点；自提省略 --mode factory
python "$skill/scripts/inventory-pending.py" --mode factory --history-root runtime --report runtime/batch-YYYYMMDD/inventory.json
# 已核实规范化数据的分配、查重和磅差计划；不改Excel
python "$skill/scripts/distribution_checks.py" --input runtime/batch-YYYYMMDD/snapshot.json --report runtime/batch-YYYYMMDD/plan.json
# 自提双归档预检，通过后同命令加 -Execute 并选新结果文件
& "$skill/scripts/archive-delivery-notes.ps1" -ManifestPath runtime/batch-YYYYMMDD/manifest.csv -ReportPath runtime/batch-YYYYMMDD/preflight.csv
# 厂发归档预检，通过后加 --execute 并选新结果文件
python "$skill/scripts/archive_factory_notes.py" --manifest runtime/batch-YYYYMMDD/factory.json --report runtime/batch-YYYYMMDD/factory-preflight.json
```

JSON格式与匹配规则见 [配送录入及同步](.agents/skills/process-delivery-notes/references/distribution-workflow.md)，自提CSV格式见 [清单说明](.agents/skills/process-delivery-notes/references/manifest-schema.md)。只读计划通过不等于已录入；保存和磁盘回读核验通过后才可归档清理。

## 回归测试

测试在临时目录使用合成记录，不读写真实业务文件。新增业务规则及厂发归档38项测试，自提归档15个场景，另保留历史盘点及图片版本恢复测试。

```powershell
python .agents/skills/process-delivery-notes/scripts/test_distribution_workflow.py
python .agents/skills/process-delivery-notes/scripts/test-inventory-history.py
python .agents/skills/process-delivery-notes/scripts/test-reviewed-version.py
& .agents/skills/process-delivery-notes/scripts/test-archive-delivery-notes.ps1
```

## 版本及数据边界

通过新增Git提交迭代。同名文件的最新内容会更新，旧内容保留在提交历史中，可比较或恢复；不需要删除旧提交或强制推送。

仓库只保存代码、规范和示例配置。真实单据、台账、核对结果、项目映射、批次日志、备份、本机路径和密钥不上传。模拟测试通过不代表真实新批次已完成，模糊识别、采购矛盾或未确认日期仍需逐笔核实。
