# v6.2 因果日线纠偏研究执行任务 v1.0 FINAL

状态：`FINAL_BEFORE_V6_2_RESULTS`  
研究标签：`v6_2_PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`  
有效完整历史场景：12  
完整历史 attempt 上限：14（12 个有效结果 + 2 个失败储备）

## 0. 本轮唯一目标

本轮只修复并重新评估 v6.1 审计确认的五项问题：

1. vendor-open 使用执行日完整 `high/low` 决定开盘订单是否成交，形成执行层未来信息过滤；
2. P0/P1/P2 因日内区间规则结构性退化，无法识别一价政策影响；
3. 1/3 tick 与 next-close 实验同时改变拒单机制，无法作干净单因素解释；
4. 可得供应商逐日保证金没有真正合入完整历史引擎；
5. 换手、成本分项、next-close 成本展示、挑战集和 AL 集中度存在报告口径问题。

本轮不优化信号、袖套权重、品种、风险预算、调仓频率、buffer、目标波动率或成本参数；不运行 v6 的 A01/44 场，不进入 v5，不购买或伪造 `ft_limit`、分钟和盘口数据。

## 1. 开始前必须完整读取

1. 本文件；
2. `docs/v6_2_causal_daily_only_correction_plan/00_README_AND_AUTHORITY.md`；
3. `outputs/v6_1_postrun_audit_20260906_210510/V6_1_POST_RUN_INDEPENDENT_AUDIT.md`；
4. `outputs/v6_1_postrun_audit_20260906_210510/audit_findings.csv`；
5. `outputs/v6_1_20260906_155224/V6_1_ENGINE_AUDIT.md`；
6. `outputs/v6_1_20260906_155224/V6_1_BACKTEST_RESULT_REPORT.md`；
7. `outputs/v6_1_20260906_155224/V6_1_DETAILED_RESULT_ANALYSIS.md`；
8. `docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml`；
9. `docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml`；
10. v3、v4.2、v6.1 正式白名单结果、相关代码和测试。

不得修改或覆盖任何 v2、v3、v4、v4.1、v4.2、v6、v6.1 源码、配置、缓存、账本、审计和输出。所有新增实现必须位于：

```text
src/five_sector_momentum/v6_2/
configs/five_sector_momentum_v6_2.yaml
data/v6_2/
tests/v6_2/
docs/v6_2_causal_daily_only_correction_plan/
outputs/v6_2_<唯一时间戳>/
outputs/V6_2_GLOBAL_ATTEMPT_LEDGER.csv
```

## 2. 证据等级与强制禁语

所有结果必须标记：

```text
research_status = PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION
execution_reference = VENDOR_DAILY_OPEN_PROXY
intraday_fill_path_observed = false
official_limit_coverage = NOT_AVAILABLE
historical_session_verified = false
queue_and_fill_probability_observed = false
margin_evidence = VENDOR_DAILY_UNVERIFIED_LAGGED_FLOORED_BY_STATIC_FALLBACK_OR_STATIC_FALLBACK_PROXY
eligible_for_live_execution_calibration = false
```

不得把结果描述为真实开盘成交、真实涨跌停、真实盘口冲击、官方历史保证金、真实强平或可直接实盘。

本轮“因果”仅指：**订单是否成交、成交数量和成交成本不读取执行时点之后才产生的日线字段**；不代表日线模型已经还原了微观成交过程。

## 3. 固定策略与共同经济参数

只允许两个策略：

1. `reference_v3_252`；
2. `sleeve_20skip5_250_equal_risk`，20 日跳过 5 日与 250 日固定 50/50 风险预算。

除本规范明确修正的执行和保证金数据路径外，全部经济参数逐字段继承 v6 v1.4：

- 2014-01-01 warmup，2015-01-01 至 2026-08-31 回测；
- 初始资金 1,000 万元；
- 27.5% 目标波动率；
- 五板块各 20% 风险预算，未使用预算不转移；
- Panama 绝对点差收盘信号、修复后的因果周度日历；
- 35 日点波动率、63 日组合波动反馈、252 日协方差缩放；
- 10% buffer、120% 紧急波动率阈值；
- 5% 滞后成交量参与率、部分成交、市场冲击、换月额外 tick；
- 商品 65% 保证金目标、总账户 78% 保证金目标、商品 8 倍名义杠杆；
- 国债不受商品名义杠杆限制但进入总保证金目标；
- 65%/78% 只约束标准目标，不实现经纪商强平；权益小于等于零写 `ACCOUNT_INSOLVENT` 并停止；
- 修正 `/1000` 比例费率、T 固定费特例、客户乘数 1.5、开仓/平昨/平今、跨零反手及换月双边收费。

## 4. Phase A：结果前数据和实现可行性

任何新增绩效产生前完成以下只读工作：

1. 验证 v6.1 原结果、注册表和关键表哈希；
2. 读取 `data/v3/fees/tushare_fut_settle_daily_raw.pkl`，独立审计字段、单位、日期、重复键和覆盖；
3. 建立规范化保证金表，只保留 `trade_date`、真实合约、方向费率、来源与证据哈希；
4. 对费率单位执行显式转换和范围检查，禁止凭数值大小静默猜单位；
5. 测量两个策略旧持仓键、旧目标键和全市场映射键上的逐日供应商覆盖；
6. 建立 12 个已知主力一价形态日和 2025-04-07 RU2505 旧腿的具体挑战夹具；这些仍不是官方限价真值；
7. 证明新的开盘成交接受函数不读取执行日 `high`、`low`、`close`、`settlement`、最终 `volume` 或最终 `oi`。

如果无法安全判定保证金单位或无法建立至少一日滞后的 as-of 合并，只能停止并输出 blocker，不得用未验证日率替代 fallback。

## 5. Phase B：结果前冻结注册表

Phase A 通过后、查看任何 v6.2 绩效前，创建并冻结：

```text
docs/v6_2_causal_daily_only_correction_plan/V6_2_MACHINE_REGISTRY.yaml
docs/v6_2_causal_daily_only_correction_plan/V6_2_EXPERIMENT_REGISTRY.md
configs/five_sector_momentum_v6_2.yaml
docs/v6_2_causal_daily_only_correction_plan/V6_2_REGISTRY_FREEZE.json
```

机器注册表必须锁定：12 个场景、两个策略、sequence 1—12、14 次 attempt 上限、全部继承参数、执行字段白名单、保证金 lag 规则、来源优先级、费用规则、测试阈值、停止条件和报告禁语。必须记录规范化保证金表和挑战夹具的内容哈希。

## 6. 因果 vendor-open 执行规范

### 6.1 成交接受字段

订单在 t 日完成信号和目标计算，在下一交易日 d 执行。d 日成交接受和数量只能使用：

- 已知交易日历和合约上市状态；
- d 日有限的 `vendor_daily_open`；
- 截至 t 日已经确定的订单；
- 截至 t 日可得的滞后流动性统计与参与率容量；
- 截至 t 日可得的保证金和账户状态。

不得使用 d 日完整 `high/low/close/settlement/volume/oi` 决定是否成交或成交多少。d 日收盘、结算价只用于当日成交后的盯市和事后诊断。

### 6.2 滑点记账

主基准采用：

```text
fill_reference_price = vendor_daily_open
fill_accounting_price = vendor_daily_open
slippage_cash_cost = lots × total_ticks × tick_size × point_value
```

其中 `total_ticks = base + roll_extra + impact`，只扣一次。成交价格保持交易所 tick 网格；现金滑点是代理成本，不称为观察到的成交价差。

不得再以 `open ± ticks` 是否超出最终日内区间决定成交，不得裁剪到 high/low，也不得同时把不利价差嵌入毛盈亏并再次扣现金成本。

### 6.3 成交量与部分成交

参与率容量必须使用 t 日可得的滞后中位成交量，不能使用 d 日最终成交量决定开盘手数。若 d 日 open 缺失则拒单；执行后发现 d 日最终 volume 为零或一价形态，只进入事后异常诊断，不回写成交路径。

### 6.4 一价形态的定位

在没有官方 `ft_limit` 的情况下，`high==low` 只能是执行后的 OHLC 形态：

- 不进入 v6.2 正式开盘成交接受函数；
- 不生成 `REJECTED_LIMIT`；
- 只输出命中订单、方向、名义额、首日 P&L 和挑战夹具回放；
- 可以计算冻结事件的 ex-post 风险区间，但不得据此构造正式权益曲线或称为因果反事实。

## 7. 保证金合并规范

### 7.1 时间规则

对 t 日目标计算，只允许使用 `trade_date <= t 的前一交易日` 的最近供应商费率；不得回填未来值，不得使用全样本后验均值。最大陈旧期固定为 **5 个交易日**；超过后使用静态 fallback。

### 7.2 方向和来源

- 多头只读取滞后 `long_margin_rate`，空头只读取滞后 `short_margin_rate`；
- 对缺失方向不得用另一方向或未来记录补齐，直接使用静态 fallback；
- 方向供应商率可用时，约束计算采用 `max(滞后方向供应商率, 静态 fallback 率)`，避免供应商代理值低于冻结安全底线；
- 每个目标、持仓和保证金约束事件保存 `rate_trade_date`、`known_at`、`source_code`、原值、转换后小数和规则 ID；
- 客户乘数统一为 1.25；
- 来源只能为 `VENDOR_DAILY_UNVERIFIED_LAGGED_FLOORED_BY_STATIC_FALLBACK` 或 `STATIC_FALLBACK_PROXY`；同时记录供应商值是否实际高于 fallback 并成为约束率。

### 7.3 单因素阶梯

B01/B02 仍使用 v6.1 静态 fallback，以单独测量执行过滤修复；B03/B04 才启用滞后供应商保证金，以测量保证金路径修正。不得在 B01/B02 同时启用供应商保证金。

## 8. 精确实验矩阵

|Seq|ID|策略|执行与目的|保证金|滑点|
|---:|---|---|---|---|---|
|1|R01|参照|精确复现 v6.1 P03 已知偏差路径，仅作兼容闸门|静态 fallback|正常、嵌入式旧实现|
|2|R02|袖套|精确复现 v6.1 P04 已知偏差路径，仅作兼容闸门|静态 fallback|正常、嵌入式旧实现|
|3|B01|参照|因果 vendor-open，移除日内区间筛选|静态 fallback|正常、现金扣除一次|
|4|B02|袖套|同 B01|静态 fallback|正常、现金扣除一次|
|5|B03|参照|v6.2 正式日线参照|滞后供应商，否则 fallback|正常、现金扣除一次|
|6|B04|袖套|v6.2 正式候选袖套|滞后供应商，否则 fallback|正常、现金扣除一次|
|7|S01|参照|低滑点敏感性|同 B03|固定 1 tick 基础滑点，其他分项不变|
|8|S02|袖套|低滑点敏感性|同 B04|固定 1 tick 基础滑点，其他分项不变|
|9|S03|参照|高滑点敏感性|同 B03|固定 3 tick 基础滑点，其他分项不变|
|10|S04|袖套|高滑点敏感性|同 B04|固定 3 tick 基础滑点，其他分项不变|
|11|T01|参照|下一交易日 close 执行时点压力|同 B03|与 B03 同一现金滑点规则|
|12|T02|袖套|下一交易日 close 执行时点压力|同 B04|与 B04 同一现金滑点规则|

不得增加场景。R01/R02 不用于经济结论。B01→B03、B02→B04 只允许保证金数据路径改变；B03→S01/S03、B04→S02/S04 只允许基础滑点 tick 改变；B03→T01、B04→T02 只允许参考时点及新仓 P&L 生效边界改变。

## 9. 强制闸门与顺序

1. **G0-SCOPE**：旧路径哈希和 secrets 检查；
2. **G1-DATA**：保证金规范化、单位、覆盖、lag 和挑战夹具通过；
3. **G2-REGISTRY**：12/2/14 计数与机器注册表冻结；
4. **G3-TESTS**：单元、迷你市场、前缀、账户和旧路径保护测试通过；
5. **G4-REPRODUCTION**：按顺序运行 R01/R02，逐表复现 v6.1 P03/P04；
6. **G5-EXECUTION-CORRECTION**：运行 B01/B02；
7. **G6-MARGIN-INTEGRATION**：运行 B03/B04；
8. **G7-SLIPPAGE**：运行 S01/S02/S03/S04；
9. **G8-TIMING**：运行 T01/T02；
10. **G9-RELEASE**：12 场景、账户、attempt、CSV/pickle、manifest、禁语与秘密扫描齐全。

任一闸门失败立即停止，不继续消耗场景。

## 10. 必须新增的测试

至少覆盖：

1. 修改 d 日 high/low 不改变 vendor-open 的成交接受、数量、参考价和现金滑点；
2. 修改 d 日 close/settlement 只能改变盯市 P&L，不能改变开盘成交；
3. 修改 d 日最终 volume/OI 不改变开盘成交数量；
4. 修改未来价格、保证金和合约数据不改变历史订单与成交；
5. 成交接受函数字段访问白名单；
6. open 现金滑点与线性不利成交价在迷你市场上的代数等价性；
7. 基础、换月和冲击滑点只扣一次；
8. 对同一已形成订单和同一账户状态，1 tick/3 tick 不得改变当次成交资格和可成交手数，只能改变现金成本；完整历史允许因成本影响权益而在之后自然产生路径反馈；
9. next-close 与 vendor-open 除时点和生效边界外参数一致；
10. next-close 新仓不获得执行日收益；
11. 保证金至少滞后一交易日，未来追加不改变过去 as-of 值；
12. 多空方向费率、静态 fallback、最大陈旧期和 1.25 倍乘数手算；
13. 每个保证金键都有来源码和 rate date；
14. 商品/总账户目标约束、国债豁免和权益耗尽；
15. 开仓、平昨、平今、跨零反手、换月双边费用；
16. sleeve 内部虚拟净额不收费，真实合约净订单才收费；
17. 12 个主力一价形态日和 RU2505 旧腿具体回放；
18. 账户权益、逐品种 P&L、手续费、现金滑点逐日勾稽；
19. 换手的初始资金与平均权益两种分母手算；
20. 成本分项必须乘 `tick_size`；
21. 确定性复跑、排序键、哈希序、secrets 和旧路径保护。

## 11. 评价规则

不以收益最高选择方案。只判断以下预注册问题：

1. 移除未来区间筛选后，P03/P04 的绝对收益被修正多少；
2. 袖套相对参照的优势是否仍存在，最大回撤是否仍改善；
3. 差异化出界拒单曾解释多少旧优势，纠偏后首次路径差异在哪里；
4. 供应商保证金接入是否显著改变目标、成交、利用率和权益；
5. 1/3 tick 在固定接受路径下是否改变策略排序；
6. open/close 在对称执行规则下是否改变策略排序；
7. 袖套是否仍存在 AL、农业、T、2020/2024 和多头集中；
8. 全样本、2015—2021、2022—2026 历史重复验证期是否方向一致；
9. 删除 2020、删除 2024、同时删除两年后是否结构性失效；
10. 现有证据是否足以支持购买 `ft_limit`/分钟数据的边际价值。

如果 B04 在全样本或历史验证期不再优于 B03，或者纠偏后最大回撤不再改善，应明确写“v6.1 的袖套优势未通过因果日线纠偏”。如果 B04 仍优于 B03，也只能写“在日线开盘代理下通过初步纠偏”，不能升级为实盘结论。

## 12. 报告口径修正

必须同时输出：

- `turnover_on_initial_capital`；
- `turnover_on_average_daily_equity`；
- 成本分项人民币金额：`ticks × tick_size × point_value × abs(lots)`；
- 嵌入式滑点诊断与实际现金扣除分列，不得相加冒充已扣成本；
- AL/FG 的正贡献占比、绝对贡献占比、净利润占比三种分母；
- 保证金 `vendor/fallback` 使用率必须按实际引擎键统计，而非只复制预检覆盖；
- 一价挑战集每条具体日期、合约、方向、是否命中订单和状态。

## 13. 输出要求

至少生成：

```text
V6_2_MACHINE_REGISTRY.yaml
V6_2_EXPERIMENT_REGISTRY.md
V6_2_REGISTRY_FREEZE.json
V6_2_ENGINE_AUDIT.md
V6_2_BACKTEST_RESULT_REPORT.md
V6_2_V61_CORRECTION_BRIDGE.md
V6_2_FINAL_STATUS.json
scenario_parameters.csv/.pkl
scenario_metrics.csv/.pkl
annual_metrics.csv/.pkl
sector_contribution.csv/.pkl
instrument_contribution.csv/.pkl
long_short_contribution.csv/.pkl
orders.csv/.pkl
fills.csv/.pkl
positions.csv/.pkl
daily_equity.csv/.pkl
rejections.csv/.pkl
cost_attribution_cny.csv/.pkl
turnover_metrics.csv/.pkl
execution_causality_checks.csv/.pkl
v61_rejection_bias_bridge.csv/.pkl
margin_normalized_rules.csv/.pkl
margin_engine_usage.csv/.pkl
margin_constraint_events.csv/.pkl
one_price_shape_diagnostics.csv/.pkl
challenge_set_replay.csv/.pkl
accounting_reconciliation.csv/.pkl
test_results.csv/.pkl
attempt_ledger_snapshot.csv/.pkl
modified_files.csv/.pkl
secret_scan_findings.csv/.pkl
manifest.json
```

所有报告表必须指向底层文件；CSV/pickle 内容一致；配置、代码、输入和输出记录 canonical 哈希。

## 14. 停止条件

出现下列任一情况立即停止并出 blocker：

- R01/R02 无法精确复现 v6.1 P03/P04；
- vendor-open 成交接受或数量读取执行日 high/low/close/settlement/final volume/final OI；
- 在相同订单、账户和滞后容量输入下，1/3 tick 改变当次订单成交资格或手数；
- next-close 除时点和 P&L 生效边界外改变其他经济参数；
- 保证金单位、lag、方向或来源无法证明；
- 同一滑点被嵌入价格并再次现金扣除；
- 费用、换月、反手或账户勾稽失败；
- 权益小于等于零后继续生成合成收益；
- attempt 超出 14；
- token 泄露或旧版本文件被修改。

## 15. 最终必须回答

1. 移除执行层未来区间筛选后，参照和袖套各损失多少收益，回撤如何变化？
2. 袖套相对参照的 CAGR、Sharpe、最大回撤优势是否仍然存在？
3. v6.1 差异化拒单对旧袖套优势的解释程度，与审计的 33.1% 诊断是否一致？
4. 供应商逐日保证金实际被引擎使用多少，fallback 多少，是否改变真实目标路径？
5. 固定 1/3 tick 是否在完全相同接受路径下改变策略排序？
6. 对称规则下 vendor-open 与 next-close 是否改变策略排序？
7. AL、农业、T、2020/2024 和多头集中是否改善？
8. 哪些结论仍受 `ft_limit`、分钟、盘口和官方保证金缺失限制？
9. 是否值得购买数据权限并返回 v6 正式路径？

完成 v6.2 后停止，不进入其他研究。
