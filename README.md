# Automatically enter delivery Notes

钢材送货单处理技能，覆盖自提运输台账、厂发直接录入配送台账，以及四本运输台账向2026配送台账同步。

流程入口为 [.agents/skills/process-delivery-notes/SKILL.md](.agents/skills/process-delivery-notes/SKILL.md)，简要功能见 [功能说明.txt](功能说明.txt)。图片识别、采购证据核对和工作簿写入由Codex配合可用工具完成；脚本提供只读匹配检查及归档，不是独立的一键OCR应用。

## 本次迭代

- 增加月末台账及照片备份清理：默认预览，显式执行，逐文件核验及记录日志；支持厂发、自提、保留旧版照片和后续批次解决待核项。
- 修复自提子目录漏扫及剩余数量统计，查重支持实际 `outputs/delivery-batch-*` 和旧批次目录。
- 同一完整单号的全部材料统一核验到货日期，各明细仍按各自计划日期匹配入库记录。
- 保留厂发直接配送、历史运输同步、行高列宽与公式保护、更正标红及保存后回读规则。

## 配置

Windows、PowerShell、Python 3.12或以上。只读旧Excel扫描依赖`openpyxl`；新分配和厂发归档脚本使用Python标准库。实际工作簿写入需可用的Excel连接或表格文件工具。

1. `python -m pip install -r requirements.txt`
2. 将技能内`assets/settings.example.json`复制为`assets/settings.json`，填写本机路径。已有配置需补充`self_pickup_pending_root`、`backup_batch_root`、`factory_pending_root`、`distribution_ledger`和`procurement_root`。
3. 将`references/project-map.example.csv`复制为`references/project-map.csv`，填写已确认映射；真实映射只留本地。
4. 在Codex中使用`$process-delivery-notes`，明确厂发/自提/历史同步范围。批次资料保存在配置的`backup_batch_root/delivery-batch-YYYYMMDD-HHMMSS`，先创建批次目录；处理前备份放在其`backups`子目录。

## 入口命令

```powershell
$skill = '.agents/skills/process-delivery-notes'
$config = Get-Content -LiteralPath "$skill/assets/settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = $config.backup_batch_root
$batch = Join-Path $runtime ('delivery-batch-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $batch -Force | Out-Null
# 只读盘点；自提省略 --mode factory
python "$skill/scripts/inventory-pending.py" --mode factory --history-root "$runtime" --report "$batch/inventory.json"
# 已核实规范化数据的分配、查重和磅差计划；不改Excel
python "$skill/scripts/distribution_checks.py" --input "$batch/snapshot.json" --report "$batch/plan.json"
# 自提双归档预检，通过后同命令加 -Execute 并选新结果文件
& "$skill/scripts/archive-delivery-notes.ps1" -ManifestPath "$batch/manifest.csv" -ReportPath "$batch/preflight.csv"
# 厂发归档预检，通过后加 --execute 并选新结果文件
python "$skill/scripts/archive_factory_notes.py" --manifest "$batch/factory.json" --report "$batch/factory-preflight.json"
```

JSON格式与匹配规则见 [配送录入及同步](.agents/skills/process-delivery-notes/references/distribution-workflow.md)，自提CSV格式见 [清单说明](.agents/skills/process-delivery-notes/references/manifest-schema.md)。只读计划通过不等于已录入；保存和磁盘回读核验通过后才可归档清理。

## 月末清理

规则和批次证据格式见 [备份清理](.agents/skills/process-delivery-notes/references/backup-cleanup.md)。已获用户授权的环境可将已有月末任务更新为调用清理脚本；仓库本身不创建定时任务。

```powershell
# 报告放在批次目录之外，每次使用新文件名；默认只预览
& "$skill/scripts/cleanup-delivery-backups.ps1" -ReportPath "$runtime/cleanup-preview-YYYYMMDD-HHMMSS.json"
# 月末按既有授权执行时，选另一个新报告路径并加 -Execute
```

仅登记且已完成核验的备份可以清理。证据缺失、归档或备份变化时保留；正式台账、正式归档和审计记录持续保留。`-AsOf`只能模拟预览，不能与`-Execute`一起使用。延迟到次月运行时保留新月份备份。

## 回归测试

测试仅使用临时目录中的合成数据。统一入口包括 71 项 Python 检查（含历史盘点和版本恢复）及 15 个 PowerShell 归档场景。

```powershell
& .agents/skills/process-delivery-notes/scripts/run-tests.ps1
# 使用指定的 Python 环境时加 -PythonPath <python.exe绝对路径>
```

## 版本及数据边界

通过新增Git提交迭代。同名文件的最新内容会更新，旧内容保留在提交历史中，可比较或恢复；不需要删除旧提交或强制推送。

仓库只保存代码、规范和示例配置。真实单据、台账、核对结果、项目映射、批次日志、备份、本机路径和密钥不上传。模拟测试通过不代表真实新批次已完成，模糊识别、采购矛盾或未确认日期仍需逐笔核实。
