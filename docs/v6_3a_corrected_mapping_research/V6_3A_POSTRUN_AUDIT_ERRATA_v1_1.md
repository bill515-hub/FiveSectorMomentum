# v6.3a 运行后独立审计勘误 v1.1

状态：`APPEND_ONLY_POSTRUN_ERRATA`

本文件不修改 `V6_3A_MACHINE_REGISTRY.yaml`、`V6_3A_REGISTRY_FREEZE.json` 或任何既有回测结果。它只规定后续引用 v6.3a 时应采用的审计口径。独立审计及全部底表位于：

`outputs/v6_3a_independent_audit_20260907_180842/`

## E01：Westfall—Young正式表替换

主运行 `analysis/westfall_young_paired_tests.*` 的实现是共同 single-step max-t，并使用Bootstrap标准差，不能按文件名解释成严格的step-down检验。

后续正式引用应使用：

`outputs/v6_3a_independent_audit_20260907_180842/audited_westfall_young_stepdown.*`

该表采用HAC(19)观测尺度和逐步缩小剩余假设族的step-down max-t。验证期 `T01-G02` 调整后p约0.101，未达到FWER 10%阈值；这不改变预注册否决项8失败和“不用三袖套替换双袖套”的结论。

## E02：基座引擎配置冻结缺口

运行代码实际解析 `configs/five_sector_momentum_v4_2_repaired.yaml`，但原freeze只冻结了薄配置 `configs/five_sector_momentum_v6_3a.yaml`，未把前者写入 `input_hashes`。这是可复现性治理缺口，不是已发现的数值错误。

审计时基座配置SHA-256为：

`45c373b25c49d742a44ccbc971dd703a89b7926ca0faeb3ed819e65fef7030bd`

该文件修改时间早于首个attempt，且审计时Git对该文件无差异。这是缓解证据，不是运行时字节的追溯性密码学证明。不得反向改写原freeze为“已覆盖”。后续版本必须把最终解析后的完整经济配置及全部递归基座配置纳入结果前freeze。

## E03：净额成本节约的可测性

现有底表可精确证明：内部袖套虚拟目标不收费、真实合约目标发生净额抵消、预约束目标变化手数下降。但没有保存每个袖套经过共同缩放、流动性约束和buffer后的反事实独立订单流，因此不能精确给出“若不净额会多付多少人民币成本”。

原推荐条件7应解释为 `PARTIALLY_TESTABLE`。任何人民币节约数字只能称指示性代理，不能称账户已实现的精确反事实节约。

## E04：固定tick跨版本比较

G01/G02的固定1/3 tick压力基线来自v6.2旧映射，而T02/T03使用v6.3a修复映射。因此该比较包含映射vintage差异，只能支持方向性敏感度，不能称严格同映射单因素。

## E05：G01与S07结构说明

独立审计否定“G01与S07使用不同选择/风险结构”的说法。两者均使用 `BacktestEngineV63`，横截面/绝对动量结构、风险预算、费用、保证金和执行完全相同；策略层唯一差异是252日与250日观察窗。两者期末差异来自少量信号、排名和方向变化经离散手数、buffer、风险缩放及权益反馈放大。

## E06：报告名称与策略含义

后续报告不得只用G01、S03、T01等代码指称策略。至少同时给出中文策略名称、信号窗口、是否skip、袖套预算和执行/成本口径。完整字典见独立审计目录的 `strategy_catalog.*`。

