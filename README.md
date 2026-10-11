# Automatically enter delivery Notes

钢材自提送货单处理工作流：图片核对、运输台账录入、保存验证、双目录归档、SHA-256校验及待处理原图清理。

简要功能见 [功能说明.txt](功能说明.txt)。当前版本是供Codex使用的技能和脚本，图片识别及实时Excel操作由Codex与连接工具完成；尚未包含独立应用界面或SQLite数据库。

## 文件结构

- `.agents/skills/process-delivery-notes/SKILL.md`：流程入口。
- `references/`：编号规则、项目映射示例、保存关闭规范和恢复规范。
- `scripts/`：图片盘点、只读对账、双目录归档、已确认图片版本替换和回归测试。
- `assets/`：本地配置示例和批次清单模板。

## 配置与使用

使用Windows、PowerShell及Python 3.11或以上；只读扫描Excel依赖`openpyxl`。实时台账编辑另需Microsoft Excel及可用的Codex/ChatGPT Excel连接和窗口控制工具。

1. 安装Python依赖：`python -m pip install -r requirements.txt`。
2. 将技能内`assets/settings.example.json`复制为`assets/settings.json`，填写本机四个目录路径。
3. 将`references/project-map.example.csv`复制为`references/project-map.csv`，填写已确认的项目、工作表和两套归档目录对应关系。沿用已有业务映射时请在本地复制，勿提交到公开仓库。
4. 在Codex中打开本项目，使用`$process-delivery-notes`处理新批次。运行报告保存在本地`runtime/batch-YYYYMMDD`；目录需先建立。
5. 台账保存并通过磁盘回读后，先预检查归档清单，再正式执行。归档脚本本身不编辑Excel。

```powershell
$skill = '.agents/skills/process-delivery-notes'
python "$skill/scripts/inventory-pending.py" --history-root runtime --report runtime/batch-YYYYMMDD/inventory.json
& "$skill/scripts/archive-delivery-notes.ps1" -ManifestPath runtime/batch-YYYYMMDD/manifest.csv -ReportPath runtime/batch-YYYYMMDD/preflight.csv
# 核对预检查无阻塞后：
& "$skill/scripts/archive-delivery-notes.ps1" -ManifestPath runtime/batch-YYYYMMDD/manifest.csv -ReportPath runtime/batch-YYYYMMDD/result.csv -Execute
```

编号、项目、日期和数量等关键内容需可靠确认。空车牌允许留空；不同实物单据的重复编号使用`-1/-2`，同一单据多条明细保持同一编号。通过实时与磁盘回读、双目录哈希校验后才能清理原图。

## 测试

测试使用临时合成数据，不读写真实业务文件。

```powershell
python .agents/skills/process-delivery-notes/scripts/test-inventory-history.py
python .agents/skills/process-delivery-notes/scripts/test-reviewed-version.py
& .agents/skills/process-delivery-notes/scripts/test-archive-delivery-notes.ps1
```

本仓库仅保存代码、规范和示例配置。真实单据、台账、项目对应表、批次日志、备份和密钥应保留在本地。
