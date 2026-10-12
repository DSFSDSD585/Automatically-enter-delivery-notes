# 自提运输操作接口

业务规则唯一来源：[送货单业务逻辑规则](送货单业务逻辑规则.md)。每次执行先按[状态工具接口](processing-state.md)实际读取规则和共享状态。

1. 通过 inventory-pending.py 获取稳定清单；真实识图后选择当前项目/承运商工作表。
2. 使用当前已发布Excel工具schema，不能猜旧会话参数。Office.js复制用destination.copyFrom(source, copyType)，不要使用source.copyTo。
3. 写前读取目标范围及相邻模板；备份、查重、编号和格式遵守规则R03–R27。写后逐字段及公式回读。
4. 保存释放按save-close-workflow.md。CSV构造见manifest-schema.md；归档先预检再Execute。
5. 运输、配送、照片、归档各阶段独立checkpoint；归档CSV中的运输saved不能表示配送同步完成。
