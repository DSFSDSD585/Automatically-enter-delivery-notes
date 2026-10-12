# Automatically enter delivery Notes

钢材送货单处理技能，覆盖自提运输台账、厂发直接录入配送台账，以及四本运输台账向2026配送台账同步。

流程入口为 [.agents/skills/process-delivery-notes/SKILL.md](.agents/skills/process-delivery-notes/SKILL.md)，简要功能见 [功能说明.txt](功能说明.txt)。图片识别、采购证据核对和工作簿写入由Codex配合可用工具完成；脚本提供只读匹配检查及归档，不是独立的一键OCR应用。

## 本次迭代

- 将检索、采购核对、磅差、录入、更正、格式保护、归档与清理规则统一到《送货单业务逻辑规则》，参考文件只维护操作接口。
- 增加独立SQLite处理状态、持续问题清单、阶段报告与专项确认；按对象、明细、检查事项分别记录，历史导入与实际复核分开。
- 开始和恢复时实际读取完整规则、最新处理、全部未解决问题及本次单据历史；规则或共享状态变化时重新核对。
- 备份清理增加关联问题与启动读取检查；保留月末预览、哈希验证、路径限制和逐文件日志。
- 公共版本不包含真实项目映射、具体历史单号或处理结论；历史导入通过本地数据接口完成。

## 配置

Windows、PowerShell、Python 3.12或以上。只读旧Excel扫描依赖`openpyxl`；分配、归档和SQLite状态工具使用Python标准库。实际工作簿写入需可用的Excel连接或表格文件工具。

1. `python -m pip install -r requirements.txt`
2. 将技能内`assets/settings.example.json`复制为`assets/settings.json`，填写本机路径；其中`state_root`必须为独立的绝对路径，不能与`backup_batch_root`相互包含。
3. 在本地部署的[业务规则附表](.agents/skills/process-delivery-notes/references/送货单业务逻辑规则.md)维护已确认映射，再运行`python .agents/skills/process-delivery-notes/scripts/rules_data.py --write`。CSV及JSON均为派生文件，不单独修改。发布版只有待确认的示例项目；真实附表与派生映射只留本地，上传时使用脱敏版本。
4. 首次用`delivery_state.py init`初始化独立状态目录，按[状态接口](.agents/skills/process-delivery-notes/references/processing-state.md)导入已核实的历史记录。已有状态库异常时先恢复，不能新建空库代替。所有命令读取同一settings.state_root，或显式传`--state-dir`。
5. 每次处理先`read-context`、逐页`read-page`、再`begin`；实际读完全部输出才继续。每阶段`record`，结束或中断`finish`。历史导入不会挤掉最新实际处理，也不能把照片归档当成配送完成。
6. 在Codex中使用`$process-delivery-notes`，明确厂发/自提/历史同步范围。批次资料保存到配置的`backup_batch_root/delivery-batch-YYYYMMDD-HHMMSS`，备份放在其`backups`子目录。

## 入口命令

```powershell
$skill = '.agents/skills/process-delivery-notes'
$config = Get-Content -LiteralPath "$skill/assets/settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = $config.backup_batch_root
$batch = Join-Path $runtime ('delivery-batch-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $batch -Force | Out-Null
# 先按状态接口完成全文读取并begin；以下命令在该处理run内执行
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
# 月末按既有授权执行时，选另一个新报告路径并加 -Execute -RunId <当前run>
```

仅登记、已完成核验且无关联未解决问题的备份可以清理。缺失或未完成导入的状态库会阻断清理；业务规则、状态库、历史事件和报告永久保留。证据缺失、归档或备份变化时保留；正式台账、正式归档和审计记录持续保留。`-AsOf`只能模拟预览，不能与`-Execute`一起使用。延迟到次月运行时保留新月份备份。

## 回归测试

测试仅使用临时目录中的合成数据。统一入口包括 105 项 Python 检查（含历史盘点和版本恢复）及 15 个 PowerShell 归档场景。

```powershell
& .agents/skills/process-delivery-notes/scripts/run-tests.ps1
# 使用指定的 Python 环境时加 -PythonPath <python.exe绝对路径>
```

## 版本及数据边界

通过新增Git提交迭代。同名文件的最新内容会更新，旧内容保留在提交历史中，可比较或恢复；不需要删除旧提交或强制推送。

仓库只保存代码、规范和示例配置。真实单据、台账、核对结果、状态数据库、问题历史、专项确认、项目映射、批次日志、备份、本机路径和密钥不上传。模拟测试通过不代表真实新批次已完成，模糊识别、采购矛盾或未确认日期仍需逐笔核实。
