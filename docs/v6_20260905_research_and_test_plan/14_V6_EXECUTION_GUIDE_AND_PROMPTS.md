# v6 分阶段执行建议与可直接使用的 Prompt

版本：v1.4 FINAL  
日期：2026-09-06  
适用项目：`D:\FiveSectorMomentum`

## 1. 推荐执行方式

不要在一个无人复核的长任务里从零搭建 v6 并直接跑完 44 场。推荐分为两个明确任务：

1. **任务 A：Phase 0 + Phase 1A。** 建软件骨架、机器配置、探针和覆盖审计，只回答能否启动 A01；不得运行任何完整历史回测。
2. **任务 B：完整 v6。** 只有任务 A 输出 `READY_FOR_A01` 且人工确认关键探针后，才按 A01→I02 的预注册顺序执行。

这样不会改变研究设计，也不返还 attempt；它只是让最可能失败的数据依赖在第一笔完整历史 attempt 前暴露。

## 2. 任务 A 的执行顺序

### A.1 冻结与只读核验

1. 完整读取本计划目录全部文件；
2. 解析 `V6_MACHINE_REGISTRY.yaml`，验证版本 1.4、44 场、22 策略、12 条比较边、48 attempt 上限；
3. 记录旧代码、配置、数据和正式输出的只读哈希与 Git 状态；
4. 建 `expected_artifact_inventory`，只以版本谱系白名单中的正式 v3/v4.2 目录为兼容来源；
5. 确认没有启用 `MARGIN_CALL_LIQUIDATION`，没有合成有限责任收益曲线。

### A.2 Phase 0 最小实施

建立但不运行完整历史：

- `src/five_sector_momentum/v6/` 新包；
- `configs/five_sector_momentum_v6.yaml` resolved config；
- schema、单位 registry、旧版只读 adapter、事件/原因码；
- 项目级 attempt 账本和排他锁；
- canonical JSON 表内容哈希；
- secrets 扫描；
- 探针和迷你市场测试入口。

resolved config 必须由机器注册源逐字段生成或校验。任何经济字段差异都必须在产生结果前停止，不能形成第二套人工参数。

### A.3 Phase 1A 三项探针

1. 五所各 1 个历史、1 个活跃合约，共 10 个 `ft_limit` 权限/内容探针；
2. 2015—2020 SHFE/INE 逐合约、品种×年、商品/T 分组保证金覆盖；
3. RB/SC/M/TA/T 各 15 日，共 75 点 `next_open` session 归属核验。

探针本身不计完整历史 attempt，但每次调用、参数、返回状态、空表、异常、时间和原始哈希都必须留痕。不得把网络错误、无权限和真实空数据混成同一种状态。

### A.4 数据规则构建与闸门

- 有 `ft_limit`：核查合约、日期、价格 tick、前结算及覆盖；
- 无权限：只可用官方公告和当时有效规则做因果推导，保存 `published_at/known_time/source_url`；
- 用 `upper>=high`、`lower<=low` 做全历史必要条件检查，但不得用当日 high/low 反推开盘前限价；
- 固定一价日和 RU2505 仅作挑战集；
- 保证金静态代理不能进入正式覆盖分子；
- 75 个 open 样本各品种必须 100% 匹配预注册 session 语义。

若达到 G0-DATA-FEASIBILITY，再构建并冻结 `legacy_compat_snapshot` 与 `corrected_v6_snapshot` 的候选及差异白名单；仍不得启动 A01。

### A.5 任务 A 的唯一合法交付

输出一个唯一时间戳目录，至少包含：

- `PHASE0_1A_STATUS.json`；
- `V6_PHASE0_1A_READINESS_REPORT.md`；
- `V6_BLOCKER_REPORT.md`（仅失败时）；
- `registry_static_validation.csv/.pkl`；
- `legacy_expected_artifact_inventory.csv/.pkl`；
- `limit_endpoint_probe.csv/.pkl`；
- `margin_coverage_probe.csv/.pkl`；
- `next_open_validation.csv/.pkl`；
- 数据来源、异常与空返回明细；
- 新增文件清单、测试结果和哈希 manifest。

最终状态只能是 `READY_FOR_A01` 或 `BLOCKED_BEFORE_A01`。任务 A 完成后必须停止。

## 3. Prompt A：现在推荐使用

```text
请继续开发 D:\FiveSectorMomentum。本轮只执行 v6 v1.4 FINAL 的 Phase 0 和 Phase 1A，不运行 A01 或任何完整历史回测。

开始前完整读取并严格执行：
D:\FiveSectorMomentum\docs\v6_20260905_research_and_test_plan\ 下的全部文件。
其中 V6_MACHINE_REGISTRY.yaml 是精确机器权威；00_README_AND_AUTHORITY.md、PLAN_REVIEW_ERRATA.md、13_FINAL_AUDIT_ASSESSMENT_v6.md 和 14_V6_EXECUTION_GUIDE_AND_PROMPTS.md 共同解释最终边界。

不得修改或覆盖任何 v2、v3、v4、v4.1、v4.2 的源码、配置、缓存、审计和输出。所有实现使用新的 v6 包、配置、data/v6 子目录和唯一时间戳输出目录。不得输出或复制 Tushare token；使用项目已有安全配置，并对日志和 manifest 做 secrets 扫描。

先执行以下工作：
1. 验证 registry_version=1.4、44 个场景、22 个基础策略、12 条单因素比较边和 48 次 attempt 上限；记录计划哈希。
2. 对正式 v3/v4.2 白名单输出建立 expected_artifact_inventory；历史从未生成的表标 NOT_APPLICABLE，核心订单、持仓、权益证据缺失则报告 blocker。
3. 建立 src/five_sector_momentum/v6/ 的最小独立包、configs/five_sector_momentum_v6.yaml、schema、单位 registry、只读 adapter、事件原因码、canonical JSON 哈希、secrets 扫描、项目级 attempt 账本和排他锁。resolved config 必须由 V6_MACHINE_REGISTRY.yaml 逐字段生成或校验。
4. 严格保持 v1.4 保证金语义：65%/78% 只是目标仓位约束；日终实际超限只记录并在下一标准目标计算中降险；不得实现 MARGIN_CALL_LIQUIDATION。equity<=0 时只写 ACCOUNT_INSOLVENT、保存部分账本并停止，不得生成合成有限责任收益曲线。
5. 运行 Phase 1A 三项探针：五所 10 合约 ft_limit 权限/内容；2015—2020 SHFE/INE 保证金逐年覆盖；RB/SC/M/TA/T 各15日共75点 next_open session 归属。区分无权限、端点异常、静默空返回与真实无数据。
6. 若 ft_limit 不可用，可在不查看任何 v6 绩效的前提下尝试官方公告规则因果推导；保存生效日、published_at、known_time、来源和推导公式。high/low 只能做必要条件 oracle，不能反推开盘前限价。
7. 执行 G0 和 G0-DATA-FEASIBILITY 所需的静态测试、数据覆盖测试、前缀不变测试与迷你市场测试。不要调用完整历史 launcher，不得消耗 V6_GLOBAL_ATTEMPT_LEDGER 的完整历史 attempt。

输出 PHASE0_1A_STATUS.json、V6_PHASE0_1A_READINESS_REPORT.md、所有探针及覆盖 CSV/pickle、测试、哈希、异常明细和修改文件清单。

如果任何阻断阈值失败：输出 V6_BLOCKER_REPORT.md，状态设为 BLOCKED_BEFORE_A01，停止；不得自动降级 PROVISIONAL、不得运行 D 组或代理限价回测。

如果全部通过：状态设为 READY_FOR_A01，冻结候选 legacy_compat_snapshot/corrected_v6_snapshot 及差异白名单，停止并向我汇报；不要自行启动 A01。
```

## 4. 人工通过任务 A 后应重点看什么

按以下顺序复核：

1. 10 合约探针是否真的返回逐日限价，而不是缓存、空表或不同端点；
2. 每个有历史敞口的品种×完整年度保证金覆盖，尤其 2015—2020 SHFE/INE；
3. 75 个 `next_open` 的夜盘/日盘归属和交易日键；
4. `expected_artifact_inventory` 是否使用正式白名单，而不是临时重跑目录；
5. resolved config 中是否明确关闭保证金强平和合成有限责任曲线；
6. snapshot 差异是否只落在预注册白名单字段；
7. secrets 扫描是否没有明文 token。

只有这些都可信，才发送 Prompt B。

## 5. Prompt B：仅在 `READY_FOR_A01` 后使用

```text
请继续执行 D:\FiveSectorMomentum 的 v6 v1.4 FINAL。前一阶段已经完成 Phase 0/1A；首先只读核验上一阶段唯一时间戳目录中的 PHASE0_1A_STATUS.json 必须为 READY_FOR_A01，并验证其计划哈希、registry 哈希、两个 snapshot 候选哈希、差异白名单和全部阻断探针仍有效。若不一致或任何输入已变化，立即输出 blocker 并停止。

完整读取 D:\FiveSectorMomentum\docs\v6_20260905_research_and_test_plan\ 全部文件，以 V6_MACHINE_REGISTRY.yaml 为精确机器权威。不得修改或覆盖 v2—v4.2 或 Phase 0/1A 冻结证据，不得改变任何注册场景、顺序、参数、阈值、策略、统计法或 attempt 规则。

按 A01→A06→B01→B08→C01→C03→D01→D02→E01→E18→F01→G01→G02→H01→H02→I01→I02 的 sequence 严格执行。每个完整历史进程启动前必须通过排他锁写入项目级 V6_GLOBAL_ATTEMPT_LEDGER；任何 STARTED 都计数，始终满足 48-attempt_count >= 44-effective_count。

强制执行 G0→G0-DATA-FEASIBILITY→G1→G2→G3→G4→G5→G6→G7→G8。每个场景按事件和结算日即时勾稽，完成后独立复算。金额残差必须≤0.01元、数量残差为0、滑点只通过成交价一次、手续费只对真实净订单、内部袖套目标不收费。

保证金语义不可改变：65%/78% 只是目标仓位约束；日终实际超限是诊断并在下一标准目标计算中降险；不得生成 MARGIN_CALL_LIQUIDATION。若任一场景 equity<=0，记录 ACCOUNT_INSOLVENT、保存部分账本、顶层 FAILED_GATE 并立即停止；不得生成合成收益、排名或 Bootstrap。

A 组必须逐表复现白名单正式结果；最终权益接近但订单、成交、持仓或成本键不同不算通过。B 组严格沿机器注册的单因素边归因，并记录首次差异日期、事件和原因。任何闸门失败都保留全部产物并输出 V6_BLOCKER_REPORT.md，不继续后续场景。

只有完整 22 策略家族通过全部闸门后才能运行联合 Bootstrap、多重比较和滚动选择；不得用中途完成的有利子集。完成全部 44 个有效场景后生成预注册的中文报告、CSV/pickle、表格追溯索引、测试结果、修改文件清单和人工复核清单。机器完成只标 COMPLETE_NONCANONICAL；没有人工签名不得写 CANONICAL_V6.json。完成 v6 后停止，不进入 v6.x/v7。
```

## 6. 若任务 A 失败，下一步如何决策

只根据 blocker 类型选择，不在当前注册内自行处理：

- `ft_limit` 无权限且官方规则无法 100% 重建：考虑用户授权升级数据权限或第二供应商；
- 早期保证金不足：考虑补建交易所公告规则，或另立仅费用修正的 v6a；
- `next_open` 无法验证：先解决分钟数据/会话定义，不能含糊使用“次日日盘开盘”；
- 旧正式输出核心证据不足：另建可审计的 legacy 重建桥接，不把估算表冒充旧真值；
- registry/config 不一致：修复 Phase 0，不启动完整历史。

任何替代方案都需要新的用户授权和新的结果前注册；不能复用 v1.4 的 44 场编号后改变含义。
