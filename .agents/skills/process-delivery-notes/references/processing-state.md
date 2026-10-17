# 状态工具接口与恢复操作

业务语义全部见[送货单业务逻辑规则](送货单业务逻辑规则.md) R01–R39。本文件只说明工具和数据格式。状态目录优先读取本地settings.json的`state_root`；未配置时为用户目录下`.delivery-processing-state`，正式业务必须配置独立的绝对路径，唯一数据源为 `state.sqlite3`；Markdown为可重建视图，禁止直接编辑来关闭问题。

## 开始每次处理（包含只读核对和清理）

使用当前可用 Python，脚本位于本 Skill 的 scripts。初始化仅限首次建立，不能用空库替代已有损坏或丢失的库。

1. 先读业务规则，再执行 `delivery_state.py read-results --notes <本次完整单号...>`：生成上次处理结果的稳定快照，返回 receipt、页数、规则哈希。结果含最近 run、最近实际有结果的 run、全部未解决问题、本次单号的处理结果和专项决定。每条结果保留对象、检查项、结论、已做处理、下一步及事件序号；同一事件只显示一次，完整证据留在原记录中。旧命令 `read-context` 仅为兼容别名，输出同一结果视图。
2. 对每页执行 `delivery_state.py read-page --receipt <receipt> --page <n>`，实际阅读结果。默认每页10000字符，可用 `--page-chars 3000` 生成较小分段；截断的页须补读。`read-status --receipt <receipt>` 查看已输出/未输出页、规则/状态是否变化及 receipt 是否已使用。上下文压缩时结合本批实际阅读进度接着读未读页，不从第一页循环重读；已输出标记本身不证明已读或已核验。
3. 执行相关事项前，按结果中的事件序号调用 `read-event --seq <序号> --page <n> --page-chars 10000` 读取具体证据或原始历史字段；分页输出会报告总页数。专项决定的原始依据用 `read-decision --id <决定ID> --page <n>`。无关旧附件不作为启动必读内容，问题及历史不会因此删除或关闭。
4. `delivery_state.py begin --receipt <receipt> --scope "本次范围"`：只有结果各页已输出、规则及共享状态未变化时返回 run。开始前识别到新单号则刷新包含这些单号的结果；处理中新增单号先读其相关结果/证据，再继续核对。已有运行中的 run 且 `guard` 通过时，上下文压缩本身不要求结束并重建 run。
5. 正式业务写入、归档、源清理之前运行 `delivery_state.py guard --run <run>`。规则或共享业务状态变化则刷新结果，结束旧 run 后新建 run；真正中断恢复也先读上次结果再建 run。已读进度只用于恢复阅读，不能代替目标工作簿、原图及保存证据的实际复核。

每个阶段用 `record --run <run> --input <事件.json>`，不要积到最终一次保存。完成/中断/失败用 `finish --run <run> --status completed|interrupted|failed`。异常退出的running记录会保留；下次读取时先按中断状态核实，不直接复用旧结论。

可用全局参数 `--state-dir <目录>`、`--rules <规则文件>`；必须放在子命令之前。测试用独立目录，正式处理采用settings中的state_root。

## 事件JSON

```json
{
  "event_key": "本次run-单号-明细-检查事项-阶段唯一值",
  "object": {"key": "稳定物理单及明细身份", "note": "完整编号", "project": "项目", "scope": "此次实际核对范围"},
  "stage": "quantity",
  "check": "该明细出库吨数",
  "status": "problem",
  "checked_at": "2026-10-12T21:00:00+08:00",
  "result": "示例：运输记录2吨，配送记录1吨；双方单元格见依据",
  "action": "实际完成的检查或修改；未修改则明确写未修改",
  "next": "后续核对或等待确认内容",
  "evidence": [{"path": "原单或证据绝对路径", "sheet": "工作表", "rows": [1], "observation": "该证据说明的事实"}],
  "related_batches": []
}
```

`stage`：photo、transport、distribution、procurement、inbound、arrival、plan_date、identity、quantity、specification、weighing、archive_primary、archive_settlement、local_save、release、cloud_sync、source_cleanup、backup_cleanup、history_conflict、rule_conflict。范围任务可用“范围:批次名”作为object.note，object.key保持该范围稳定身份；不能编造真实送货单号。

`status`：ok、problem、not_checked、modified_unverified、resolved、false_positive、not_applicable。同一`object.key + check`确定永久问题号；不要用会移动的行号单独作为身份。多条相同材料使用已确认原单明细序号区分。`scope`保留原材料、日期、行号和文件范围。

实际ok/resolved/false_positive必须带`verified:true`、带时区的checked_at及非空evidence。每项证据必须含现存path、匹配文件的sha256、具体observation、kind。kind为photo_visual、workbook_disk_read、procurement_read、archive_hash、local_save_verification、release_check、cloud_sync_check、source_absence_check或cross_check。保存命令成功不是验证方式；跨表核对需同时记录双方路径、表及行。脚本核验文件存在/哈希及检查类型，代理仍负责实际看图和逐格核验。

要关闭旧问题，沿用相同key/check，显式resolved或false_positive；ok不能覆盖开放问题。用户说已改用modified_unverified，不能把用户话语当磁盘核验。not_applicable必须写明原因。新事件使用新event_key；重试相同事件复用原key及原内容，防止重复。

## 历史与报告

`import_delivery_history.py --workspace <业务工作目录> --records <本地历史记录.json>`导入已登记的历史来源；格式见下文。公共脚本不内置任何真实单号、业务结论或聊天记录。保留原文件路径/哈希/条目及原时间；不写正式台账。历史未知时间为null。报告中的无时区时间保留raw历史文字，未获确切时区证据时不补造。导入记录来源为historical_import，不成为最新实际处理。

`delivery_state.py export`重建最新处理状态、全部未解决问题、各run阶段报告和状态索引。新状态已提交而报告生成失败时，保留数据库并重跑export，不重复业务写入。阶段报告提供完整依据，源历史文件不删除。

启动列出所有专项决定的完整指示及对象；`--notes` 再读取这些单据的历次处理结果，包括已解决/撤销误报。按事项需要用 `read-event` / `read-decision` 展开原始证据。历史专项确认通过导入接口保存，不能以新上传时间覆盖旧决定。

状态损坏或缺失时先从备份/原始批次重建并复核；不悄悄新建空库继续。SQLite事务保留完整事件；较旧/时间不详的历史导入不覆盖已有实际检查。多个聊天共享状态，guard发现其他run更改后重新读取。

### 公共版历史导入格式

`--workspace`扫描该目录及其outputs下的batch-*、delivery-batch-*中的progress.json、completion.json和旧final-source-results.csv。批次完成时间单独保留，不冒充每条业务的核对时间。旧CSV不证明配送已录齐。

其他历史报告须先根据实际原报告整理为本地JSON，不能从摘要编造结果：

```json
{
  "history_scope_reviewed": true,
  "records": [{
    "source": "old-report.json",
    "sha256": "原报告的实际SHA256",
    "locator": "第1条记录或JSON路径",
    "record": {
      "event_key": "稳定历史来源及条目标识",
      "object": {"key": "示例单号:明细1", "note": "示例单号", "scope": "原报告实际核对范围"},
      "stage": "quantity", "check": "吨数", "status": "problem", "checked_at": null,
      "result": "原报告具体差异", "action": "历史结果导入，未重新复核", "next": "读取当前原单和台账"
    }
  }],
  "decisions": [{
    "source": "confirmation.json", "sha256": "确认文件的实际SHA256", "locator": "用户原话位置",
    "object": {"note": "示例单号", "scope": "指定照片版本"}, "instruction": "保留用户确认的旧版", "decided_at": null
  }]
}
```

source为绝对路径或相对该JSON的路径，导入前和结束前核验哈希。records内字段沿用事件JSON，实际核对时间不详用null；无时区时间保留原文但不冒充已知核对时间。先按证据顺序导入问题，再导入明确的解决/撤销事件；不能用ok关闭遗留问题。

只有已逐项核对历史检索范围、所有待核问题和专项确认后才设`history_scope_reviewed:true`。新环境确实没有历史时，也应先核对后提供空records/decisions及该声明。单独扫描批次或声明缺失时，清理保持阻断。中断可重跑同一输入；已落库事件保留且不会重复。本地历史JSON、来源报告及状态库不提交Git。

## 清理接口

settings增加`state_root`；备份预检查询候选批次/单号关联的开放问题及导入完整标记。缺状态或未完成导入则保留。正式清理增加`-RunId <run>`，执行前和每个删除前检查规则及共享状态；不更改已有自动任务的时间或创建新任务。独立测试settings可不配置state_root，沿用原测试清单协议，正式配置必须保留该字段。
