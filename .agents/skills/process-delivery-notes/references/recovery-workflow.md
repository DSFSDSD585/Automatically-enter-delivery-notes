# 恢复工具接口

业务规则唯一来源：[送货单业务逻辑规则](送货单业务逻辑规则.md)。每次执行先按[状态工具接口](processing-state.md)实际读取规则和共享状态。

- `reconcile-pending-delivery-notes.py --mapping <已核对ID映射.json> --history-dir <workspace> --report <新报告.json>`：映射含source_file、delivery_no、source_sha256；查四本运输和两处归档，输出候选，不自动授权删除。
- 保存后但未归档的自提记录可用save_method=existing；提供fresh ledger_sha256及逐单图片对磁盘行核验。related_suffix_records仅是候选。
- `archive-delivery-notes.ps1`：每次新ReportPath，先预检再执行；CSV及相邻.journal.jsonl记录断点。重试前重新核对实际文件及状态库，不能改哈希通过检查。
- `replace-reviewed-archive-version.py`：显式提供expected old hashes、pending hash、workbook hash、现有root及review evidence；工具先备份旧图再替换，不修改台账或删除待处理源。随后普通双归档再检并清源。
- 厂发使用archive_factory_notes.py独立JSON，不伪造自提CSV。版本、重号、缺字段及冲突判定见规则R06–R15、R28–R39。
