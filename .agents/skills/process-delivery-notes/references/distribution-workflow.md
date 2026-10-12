# 配送工具接口

业务规则唯一来源：[送货单业务逻辑规则](送货单业务逻辑规则.md)。每次执行先按[状态工具接口](processing-state.md)实际读取规则和共享状态。

## 只读计划脚本

`distribution_checks.py`输入JSON顶层含`stocks`、`existing`、`legacy`、`incoming`数组。每条业务字段：`project,seller,plan_date,material,brand,model,spec,length,mode,tons,pieces`。日期ISO，吨位用十进制字符串，件数正整数，`mode`为`factory/self_pickup`；规格尺寸统一单位，无定尺用已确认的`/`，不以空值假装确认。

stocks另有`stock_id`（如A-9）；existing另有`stock_id,note_no,arrival_date`；legacy只查重复，不计入2026余额；incoming另有唯一`line_id,note_no,arrival_date`及可选`received_tons`。同单同组多源行先汇总，line_id不可重复。

可选`distinct_note_reviewed:true`表示已比较原单、确认与不同编号的相同记录是不同物理单，不是跳过检查的随意开关。同编号同组源行完全同数量时先报疑似重复；只有原单确实有多条相同明细、已经核实才用`repeated_detail_reviewed:true`，不能把运输重复登记直接相加。盘材暂估复核用顶层`estimate_reviews`：同组字段加`delivered_tons,delivered_pieces,purchase_tons,purchase_pieces,reason`，数量必须精确对应本次计算；不是永久容差。

输入可以限定本次相关组，但stocks须包含该组全部入库编号，existing须包含这些入库编号的全部有效历史配送，不能只传本次单号已有行，否则会漏算占用余额。未规范化的日期、单位或别名先核对，不能丢弃相关异常行后假装组内余额完整。

输出`ready`只表示规范化输入符合规则，仍需核查当前文件哈希、采购和原图。`blocked/legacy_record_exists`不写。脚本不做OCR、别名识别、采购搜索或工作簿修改；这些由执行技能的代理完成。

## 厂发归档脚本

`archive_factory_notes.py`清单为`{"items":[...]}`；配置在`assets/settings.json`，测试可用`--settings`。每项需：

- `source_file,source_sha256,backup_file,backup_sha256`，源位于厂发待处理，备份与源/目标分开。
- `delivery_no,project,archive_project,arrival_date`，project为总览K实际全称，archive_project为已确认归档目录名。
- `ledger_file,ledger_sha256,ledger_sheet`，表为总览表。
- `expected_rows`数组，每项`row,cells`；cells至少含A、C、K、Q、R、S、T的磁盘实际值，日期用Excel序列。必须列齐该编号所有明细，不能只列已完成的一部分。

先不带`--execute`预检，通过后加该参数执行。脚本重读保存工作簿、比对每格及同号完整行集合、核对入库计划日期与材料，核验源/备份哈希后才归档。它不替代原图识别、完整性和项目映射判断。

仅在已存在的项目目录下创建到货年份目录。图片同名异内容或跨格式冲突保留待核；目标、备份及台账再次核验后才清理源。中断保留已成功归档；源已不存在的重试仍需核验备份、目标和台账。自提双归档仍走原PowerShell脚本，不为厂发伪造运输记录。
