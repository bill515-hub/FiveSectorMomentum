# v6.1 日线限定版执行任务规范 v1.1 FINAL

版本：`1.1 FINAL`  
状态：`LOCKED_BEFORE_NEW_PERFORMANCE_RESULTS`  
研究标签：`v6_1_PROVISIONAL_DAILY_ONLY`  
场景数：14 个有效完整历史运行  
完整历史 attempt 上限：16 次（14 个有效结果 + 2 个失败重试储备）

## 0. 权威、边界与版本关系

本文是下一次执行任务的唯一完整规范。`V6_1_MACHINE_REGISTRY.yaml` 在性能结果产生前建立并通过本文规定的静态校验后，成为参数和场景的精确机器权威。若叙述与机器注册表冲突，在冻结前必须修正；冻结后不得通过解释文字改写机器字段。

本文吸收两份执行审计中可复核且相互一致的意见，并解决以下问题：

1. v6 Phase 1A 把 Windows/网络层 `ConnectionError` 中的英文 `permissions` 误判成 Tushare 接口无权限；
2. `next_open` 的“0% 匹配”实际是 0 个可观测分钟样本，不是 75 个真实不匹配；
3. `fut_settle` 当前状态存在“可返回正数据”与“静默空表”的独立复测差异，必须以干净探针重新确认；
4. 原 v6.1 草案实际列出 14 个场景，却写成最多 12 个；本版统一为 14 个有效运行、16 次 attempt 上限；
5. 原草案没有锁定手续费口径；本版明确 R 组沿用旧错误口径只作兼容锚，P/S/C 组统一使用修正口径；
6. 保证金真实覆盖和代理使用比例必须先测量、后冻结进注册表；
7. `high==low` 代理只作用于引擎实际形成订单的真实合约及换月腿，不能扫描远月低流动性合约后生成伪执行事件。

v6 v1.4 的 `BLOCKED_BEFORE_A01`、注册表、attempt 账本、源码、配置、数据和输出保持不变。v6.1 不运行 v6 的 A01，不修订 v6 v1.4 的正式阈值，也永远不能自动升格为 v6 正式基准。

不得修改或覆盖 v2、v3、v4、v4.1、v4.2、v6 的源码快照、配置、缓存、审计和历史输出。所有新增实现使用：

```text
src/five_sector_momentum/v6_1/
configs/five_sector_momentum_v6_1.yaml
data/v6_1/
tests/v6_1/
outputs/v6_1_<唯一时间戳>/
outputs/V6_1_GLOBAL_ATTEMPT_LEDGER.csv
```

## 1. 研究目标和证据等级

v6.1 只回答：在缺少逐日官方限价和历史分钟/盘口数据时，v3 12 个月参照与 20 日跳过 5 日/250 日等风险袖套的相对表现，是否对有限、预注册的日线成交代理保持稳健。

所有运行和报告必须携带：

```text
research_status = PROVISIONAL_DAILY_ONLY
execution_evidence_level = DAILY_BAR_PROXY
official_limit_coverage = NOT_AVAILABLE
historical_intraday_session_verified = false
queue_and_fill_probability_observed = false
eligible_for_live_execution_calibration = false
```

不得使用“真实成交”“真实锁板”“已复原历史限价”“已核验夜盘开盘”“真实保证金”“真实强平”等表述。

## 2. 固定策略和共同经济参数

只运行两个固定策略：

1. `reference_v3_252`：v3 的 250/252 日参照信号；
2. `sleeve_20skip5_250_equal_risk`：20 日跳过最近 5 日与 250 日固定 50/50 风险袖套。

P/S/C 组共同参数逐字段继承 v6 v1.4 `V6_MACHINE_REGISTRY.yaml`，包括但不限于：

- 2014-01-01 warmup、2015-01-01 至 2026-08-31 回测；
- 2015—2021 样本内、2022—2026 历史重复使用验证期；
- 初始资金 1,000 万元；
- 27.5% 组合目标波动率；
- 五板块各 20% 风险预算，未使用预算不转移；
- 绝对点差信号、Panama 复权收盘价、周度信号；
- 35 日 robust EWMA 点波动率、63 日组合波动反馈、252 日协方差统一缩放；
- 10% buffer、120% 紧急波动率阈值；
- 5% 成交量参与率、部分成交、市场冲击和换月额外 tick；
- 商品 65% 保证金目标利用率、总账户 78% 目标利用率、商品 8 倍名义杠杆限制；
- T 不受商品名义杠杆上限，但进入总账户目标约束；
- 65%/78% 只约束目标头寸，日终超限只记录并在下一标准目标计算降险；
- 禁止 `MARGIN_CALL_LIQUIDATION`，权益小于等于零时写 `ACCOUNT_INSOLVENT`、保存部分账本并停止；
- 主力合约、流动性、OI、换月、风险预算和袖套净额规则均不得根据 v6.1 结果调整。

P/S/C 全部使用 v4.2 修复后的因果周度日历。R01 只按 v3 原日历复现 v3；R02 只按 v4.2 修复日历复现 v4.2 S1。R 组是适配器闸门，不能与 P 组直接做单因素经济归因。

## 3. Phase A：先修正探针证据链

任何性能结果产生前，必须新建唯一时间戳目录：

```text
outputs/v6_1_preflight_<timestamp>/
```

不得覆盖 `outputs/v6_20260906_135321_phase0_1a`。旧阻断结论保留，但新报告必须明确旧探针记录存在分类污染。

### 3.1 异常分类状态机

探针不得再按模糊关键词 `permission` 分类。必须先判断异常来自 transport、HTTP、Tushare application response 还是成功响应。

精确状态至少包括：

```text
DATA
APPLICATION_NO_PERMISSION
RATE_LIMITED
NETWORK_BLOCKED
NETWORK_ERROR
ENDPOINT_ERROR
SILENT_EMPTY
KNOWN_OUTSIDE_LISTING_RANGE
KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL
NOT_TESTABLE
```

分类要求：

- `APPLICATION_NO_PERMISSION`：仅在网络请求已经到达 Tushare、返回应用层无权限消息时使用；保存 API 名称、异常类、应用层安全消息码和消息指纹；
- `NETWORK_BLOCKED`：WinError 10013、沙箱/防火墙明确禁止套接字等；即使错误英文含 `permissions` 也不得归为接口无权限；
- `NETWORK_ERROR`：DNS、SSL、连接超时、连接重置等；
- `RATE_LIMITED`：HTTP 429 或 Tushare 明确频率限制；
- `SILENT_EMPTY`：端点成功返回且 DataFrame 为 0 行，但尚未证明是真实无数据；
- `KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL`：同一端点正控制成功后，目标合约/区间仍为空，并结合上市区间或历史覆盖证据才能使用；
- `NOT_TESTABLE`：没有可观测分母，禁止写成 0% 匹配。

网络类和限流类错误最多重试 3 次，固定等待 1、3、9 秒；应用层无权限和成功空表不重试。每次重试保存时间、错误层、异常类、WinError/HTTP 状态、安全消息码和不可逆指纹。不得保存 token、请求头或可能包含 token 的原始 URL。

### 3.2 连通性和正控制

在调用三个目标端点前，先执行一个低成本、已授权的 Tushare 基础端点连通性控制。若控制端点出现 `NETWORK_BLOCKED/NETWORK_ERROR` 且重试后仍失败，则状态为：

```text
BLOCKED_PREFLIGHT_NETWORK_EVIDENCE
```

立即停止，不冻结 v6.1 注册表，不运行任何完整历史场景。

`fut_settle` 必须至少设置：

- SHFE 正控制 `RB2410.SHF`（覆盖其实际上市交易区间，审计历史锚点约 103 行，不把 103 硬编码成当前必然行数）；
- CFFEX 正控制 `T2403.CFX`（覆盖其实际上市交易区间，审计历史锚点约 9 行，不把 9 硬编码成当前必然行数）；
- 2015—2020 实际持仓暴露的 SHFE/INE 逐合约覆盖探针。

只有正控制成功后，早期合约空表才可从 `SILENT_EMPTY` 升级为 `KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL`。

### 3.3 ft_limit、ft_mins 和 fut_settle 的判定

- `ft_limit`：若干净探针确认为 `APPLICATION_NO_PERMISSION`，记录为 v6 正式路径的真实阻断，但不阻断 v6.1 日线代理；
- `ft_mins`：若确认为 `APPLICATION_NO_PERMISSION`，历史 75 点结果记为 `NOT_TESTABLE_DATA_UNAVAILABLE`，不能报告 0% 不匹配；
- `fut_settle`：重新测量真实供应商覆盖。供应商字段与官方交易所规则分开计数，不再把“官方规则表未建”误写成供应商 0% 数据覆盖。

若 `ft_limit` 意外变为可用并能覆盖正式订单键，停止 v6.1 完整历史运行，输出 `V6_CANONICAL_DATA_NOW_POSSIBLE.md`，由用户决定是否返回 v6 v1.4。

### 3.4 近期分钟数据辅助诊断

允许尝试 AkShare/新浪等公开近期分钟数据，只用于核验近期 session 约定，不替代历史 `ft_mins`：

- RB、SC、M、TA、T 各选择一个当前/最近活跃合约；
- 每品种目标最多 15 个与 Tushare 日线重叠的近期交易日；
- 输出实际可观测数、日线 open、分钟首笔时间、分钟首价和匹配状态；
- 分母只能使用真实取到且映射成功的分钟日；
- 0 个可观测点时为 `NOT_TESTABLE`；
- 少量样本只能写 `RECENT_SESSION_CONVENTION_PARTIALLY_VERIFIED`，不能推断 2015—2026 历史逐日语义。

此诊断失败不阻断 v6.1，但必须进入可靠性限制。

### 3.5 Phase A 输出

至少输出 CSV 和 pickle：

- `connectivity_control`；
- `endpoint_attempt_log`；
- `ft_limit_probe_corrected`；
- `ft_mins_probe_corrected`；
- `fut_settle_positive_controls`；
- `margin_vendor_coverage_by_instrument_year`；
- `next_open_historical_validation_status`；
- `recent_session_convention_probe`；
- `probe_classification_regression_tests`；
- `V6_1_PREFLIGHT_EVIDENCE_REPORT.md`；
- `V6_1_PREFLIGHT_STATUS.json`。

## 4. Phase B：冻结机器注册表

只有 Phase A 网络证据链合格后，才能在查看任何 v6.1 性能结果前创建：

```text
docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml
docs/v6_1_daily_only_provisional_plan/V6_1_EXPERIMENT_REGISTRY.md
configs/five_sector_momentum_v6_1.yaml
```

机器注册表必须逐字段复制 v6 v1.4 的共同经济参数，并额外锁定：

- registry version；
- 14 个场景和 sequence 1..14；
- 16 次全局 attempt 上限；
- 两个策略 ID；
- 两套费用语义；
- 三种一字板代理政策；
- vendor-open 与 next-close 的 P&L 生效时点；
- 保证金供应商真实覆盖率、fallback 覆盖率及 Phase A 证据文件哈希；
- 代理原因码；
- 挑战集来源文件和哈希；
- 停止条件、报告禁语和证据等级；
- `LOCKED_BEFORE_NEW_PERFORMANCE_RESULTS=true`。

## 5. Phase C：兼容运行环境

R01/R02 前必须解决旧 pickle 和测试入口兼容，但不得改写旧 pickle 或旧测试。

优先顺序：

1. 选择能够读取 `data/normalized_v2/*.pkl` 的现有 Python/NumPy/Pandas 运行时；
2. 直接以 `unittest` 入口运行既有 `tests/test_v4_2_preflight.py` 和 `tests/test_v4_2_repaired.py`，避免 pytest 把顶层 `setup(data=None)` 当 xunit hook；
3. 若需要 pytest，只允许把 pytest/hypothesis 安装到项目内 `data/v6_1/runtime/`，不得升级或替换全局 NumPy/Pandas，不得修改 D 盘外部环境；
4. 保存 Python、NumPy、Pandas、PyYAML、Tushare、pytest 版本、解释器路径、依赖清单和 pickle 读取 smoke test；
5. 同一场景的所有完整历史运行使用同一解释器和同一依赖哈希。

若任何核心旧 pickle 无法读取，或既有 v4.2 因果/账户测试在兼容运行时失败，状态为 `BLOCKED_BEFORE_R01` 并停止。

## 6. 手续费双语义

### 6.1 R 组旧费用

R01/R02 必须使用旧版本实际采用的费率换算，包括历史 `/10000` 缺陷，仅用于验证只读适配器、订单、成交、持仓和权益能否忠实复现。报告必须标记：

```text
fee_semantics = LEGACY_COMPATIBILITY_ONLY_KNOWN_UNDERESTIMATION
eligible_for_economic_conclusion = false
```

### 6.2 P/S/C 组修正费用

P/S/C 全部使用 v6 已定义的修正手续费规则：

- 比例费率按已审计的 `/1000` 单位转换；
- 固定每手费用不做比例换算；
- T 的固定费特例必须单独测试；
- 客户费率为交易所标准 ×1.5；
- 区分 `OPEN`、`CLOSE_YESTERDAY`、`CLOSE_TODAY`；
- 跨零反手拆成平仓和开仓；
- 换月旧腿与新腿分别收费；
- 生效日期、来源、代理标志和规则 ID 必须落盘；
- 滑点、换月额外滑点、市场冲击和手续费各扣一次。

R→P 的费用差通过冻结 R 订单路径重新计费做纯会计桥接，不增加完整历史场景。该桥接只解释手续费直接差，不冒充包含权益—头寸反馈的完整反事实。

## 7. 保证金代理及压力披露

P/S/C 基准保证金规则固定为：

```text
lagged available vendor daily margin
else frozen v3 instrument fallback margin
customer multiplier = 1.25
```

Phase A 测得的供应商覆盖率和 fallback 比例必须写入机器注册表证据区，不能继续假设“多数日期有逐日数据”。每条目标/持仓保证金记录来源：

```text
VENDOR_DAILY_UNVERIFIED
STATIC_FALLBACK_PROXY
```

不得标成官方保证金。

不新增完整历史场景，基于每个 P03/P04 日终真实持仓和约束前目标，做 multiplier `1.00 / 1.25 / 1.50` 三档影子诊断：

- 实际保证金利用率；
- 65%/78% 越限天数；
- 若重新施加目标约束会减少的目标手数；
- 品种、板块、年份分布。

影子诊断不反馈未来权益和仓位，不得作为反事实收益曲线。若 1.00 与 1.50 导致大量目标差异，只能列为后续保证金专项研究，不得临时追加场景。

## 8. 日线成交代理及作用域

### 8.1 作用域

日线一字板代理只在引擎已经使用 t 日可得信息形成的真实订单上判断，包括：

- 当前主力合约的信号调仓订单；
- 退出、反手和波动率目标订单；
- 换月旧腿与新腿；
- 保证金或流动性目标约束产生的真实净订单。

不得因为全库远月合约出现 `high==low` 就生成拒单事件。全库一价日可以作为数据质量统计，但必须与订单命中事件分表。

固定挑战集由审计确认的主力映射 12 个一价形态日、对应旧成交段，以及 2025-04-07 RU2505 换月旧腿组成。挑战集只是回归夹具，不是真实涨跌停真值；P1/P2 只检查预注册代理政策是否按订单方向执行。

### 8.2 P0 乐观代理

有完整日线、成交量大于零且参与率允许时，按 vendor daily open 加不利滑点代理成交，不使用一字板方向拒单。

### 8.3 P1 方向性代理

当 `high == low`：

- 单一价格大于 `pre_settle`：拒绝买入侧，卖出侧允许；
- 单一价格小于 `pre_settle`：拒绝卖出侧，买入侧允许；
- 等于 `pre_settle`、`pre_settle` 缺失、成交量为零或方向不明：双向拒绝。

原因码统一为 `DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT`，不能写 `REJECTED_LIMIT`。

### 8.4 P2 保守代理

任何实际订单命中的 `high == low` 日双向拒绝，原因码为 `DAILY_ONE_PRICE_ALL_SIDE_STRESS_REJECT`。

### 8.5 非一价日及滑点价

- 本节的 `[low, high]` 可成交性规则适用于 vendor-open 的 P0/P1/P2/S 场景；C 组按 §9 的收盘代理单独处理，以保持执行时点比较的单因素性质；
- 成交价必须在 tick 网格；
- 继续施加参与率和部分成交；
- 不利滑点价若超出当日 `[low, high]`，拒单并单独标记；
- 不允许把价格裁剪回 high/low；
- 不允许用当日 high/low 改变开盘前信号、目标或品种选择；
- P1 相对旧路径的改善可能是拒掉历史极端负成交的机械结果，必须单独量化这些事件的直接贡献与路径反馈。

## 9. vendor-open 与 next-close 记账

vendor-open 场景：订单在 t 收盘后形成，下一交易日 d 按供应商 daily open 代理成交。只能称 `vendor_daily_open`，不能声称是已核验的日盘或夜盘开盘。

next-close 场景：订单在 d 收盘代理成交，新头寸从下一交易日起参与 P&L；不能获得 d 日开盘至收盘收益。旧持仓在 d 日收盘前仍承担 d 日盈亏。

为使 C 组相对 P1 只改变执行时点：非一价日以 daily close 作为代理成交参考价，原正常整数 tick 按独立现金滑点归因扣除一次，不因 `close ± ticks` 越出当日 `[low, high]` 再增加拒单；一价日仍执行 P1 方向性代理。该现金滑点不是观察到的真实价差，必须与手续费、冲击和换月额外滑点分列，并通过“只扣一次”勾稽。C 组不得同时改变参与率、费用、保证金、buffer 或其他经济参数。

必须有手算测试覆盖：开仓、减仓、反手、换月、拒单后次日重算和收盘成交的持仓生效边界。

## 10. 精确场景注册表

14 个有效完整历史场景如下，全部必须保存：

| Sequence | ID | 策略 | 日历/执行 | 一价日政策 | 滑点 | 费用 |
|---:|---|---|---|---|---|---|
| 1 | R01 | reference_v3_252 | v3 legacy vendor-open | legacy | v3 normal | legacy `/10000` |
| 2 | R02 | sleeve_20skip5_250_equal_risk | v4.2 repaired vendor-open | legacy | v4.2 normal | legacy `/10000` |
| 3 | P01 | reference_v3_252 | repaired vendor-open | P0 optimistic | normal | corrected `/1000` |
| 4 | P02 | sleeve | repaired vendor-open | P0 optimistic | normal | corrected `/1000` |
| 5 | P03 | reference_v3_252 | repaired vendor-open | P1 directional | normal | corrected `/1000` |
| 6 | P04 | sleeve | repaired vendor-open | P1 directional | normal | corrected `/1000` |
| 7 | P05 | reference_v3_252 | repaired vendor-open | P2 reject all one-price | normal | corrected `/1000` |
| 8 | P06 | sleeve | repaired vendor-open | P2 reject all one-price | normal | corrected `/1000` |
| 9 | P07 | reference_v3_252 | repaired vendor-open | P1 directional | fixed 1 tick | corrected `/1000` |
| 10 | P08 | sleeve | repaired vendor-open | P1 directional | fixed 1 tick | corrected `/1000` |
| 11 | P09 | reference_v3_252 | repaired vendor-open | P1 directional | fixed 3 tick | corrected `/1000` |
| 12 | P10 | sleeve | repaired vendor-open | P1 directional | fixed 3 tick | corrected `/1000` |
| 13 | P11 | reference_v3_252 | repaired next-close | P1 directional | normal | corrected `/1000` |
| 14 | P12 | sleeve | repaired next-close | P1 directional | normal | corrected `/1000` |

“sleeve”均指同一个固定的 `sleeve_20skip5_250_equal_risk`，不能解释成其他袖套。

## 11. Attempt 纪律

- 独立账本：`outputs/V6_1_GLOBAL_ATTEMPT_LEDGER.csv`；
- 有效场景 14；全局 attempt 上限 16；储备 2；
- 每个启动的完整历史引擎进程计一次 attempt；
- 探针、静态测试、迷你市场、纯会计桥接、保证金影子诊断不计完整历史 attempt；
- `STARTED` 后崩溃仍计一次，不返还；
- 启动前取得排他锁并检查剩余额度；
- 不得以分进程、改名或复制结果规避计数；
- 不得临时增加场景。

## 12. 执行顺序和强制闸门

### G0-EVIDENCE

- 修复探针分类；
- 网络连通性控制成功；
- `ft_limit/ft_mins/fut_settle` 得到可审计的新证据；
- 0 个分钟观测不再写成 0% 匹配；
- secrets 扫描通过。

失败即停止在 `BLOCKED_PREFLIGHT_NETWORK_EVIDENCE`。

### G1-REGISTRY

- registry v1.1；
- 14 场景、14 个 sequence 唯一；
- 2 策略；
- 16 attempt 上限；
- P/S/C 费用全为 corrected；
- R 费用全为 legacy-only；
- 所有共同参数与 v6 v1.4 逐字段一致；
- 在性能结果前锁定哈希。

失败即停止，不运行 R01。

### G2-ENVIRONMENT

- 核心旧 pickle 可读；
- 兼容解释器锁定；
- 旧 v4.2 因果、日历、账户测试可在不修改旧文件的前提下运行；
- 新 v6.1 单元和迷你市场测试通过。

失败即停止在 `BLOCKED_BEFORE_R01`。

### G3-R01/R02

按各自历史白名单输出逐表复现 orders、fills、positions、daily_equity、成本和账户勾稽。只允许预注册的非经济元数据差异。

失败即停止，不运行 P01。

### G4-P0

按顺序 P01、P02。账户、费用、滑点、换月双边和因果前缀全部通过后才能进入 P1。

### G5-P1

按顺序 P03、P04。挑战集、订单作用域和代理原因码必须通过。

### G6-P2

按顺序 P05、P06。只允许一价日政策相对 P1 改变。

### G7-SLIPPAGE

按顺序 P07—P10。除基础滑点外，与 P03/P04 的经济参数一致。

### G8-CLOSE

按顺序 P11、P12。除执行时点与持仓生效规则外，与 P03/P04 一致。

### G9-RELEASE

- 14 个有效结果齐全；
- attempt 不超过 16；
- 全场景账户勾稽；
- 所有结果都有 CSV/pickle；
- secrets 和旧路径保护检查通过；
- 报告水印和禁语检查通过。

## 13. 测试要求

至少新增：

1. WinError 10013 不会被归为无权限；
2. Tushare 应用层无权限能被准确归类；
3. HTTP 429/频控、DNS、SSL、超时、空表、真实数据分别分类；
4. 重试次数和 1/3/9 秒策略；
5. 0 个分钟观测返回 `NOT_TESTABLE`；
6. 正控制成功后空表的状态升级条件；
7. registry 14/2/16 静态计数；
8. R 与 P 的费率除数、固定费和 T 特例手算；
9. 开仓、平昨、平今、反手和换月费用；
10. 实际订单合约作用域，不因远月一价日生成拒单；
11. 12 日挑战集和 RU2505 旧腿代理分支；
12. P0/P1/P2 方向性手算；
13. 滑点价越出区间时拒单而非裁剪；
14. vendor-open 和 next-close 的 P&L 边界；
15. 收盘新仓不获得当日收益；
16. 信号、目标、选择和订单形成的未来前缀不变；
17. high/low 扰动不改变开盘前信号和目标；
18. 成本只扣一次；
19. sleeve 内部虚拟目标不收费、真实净订单才收费；
20. 账户权益、逐品种 P&L 与成本逐日勾稽；
21. 保证金三档影子诊断不反馈头寸；
22. `equity<=0` 保存部分账本并停止；
23. 确定性复跑、哈希序和 tie-break；
24. secrets 扫描和旧版本路径不变。

## 14. 结果分析规则

不得以收益最高选择执行代理。P1 是预注册的正式日线代理，P0/P2 是上下界，S/C 是敏感性。

至少评价：

- 全样本、样本内、历史重复使用验证期；
- CAGR、波动率、Sharpe、Sortino、Calmar、最大回撤和恢复时间；
- 分年度、板块、品种、多空贡献；
- 年份/板块/品种集中度和 FG 依赖；
- 成交手数、换手、手续费、基础滑点、换月滑点、冲击；
- 拒单、部分成交、重算、buffer 和换月统计；
- P0/P1/P2 的结果区间和首个路径分歧；
- 一价日代理的直接会计影响与权益—仓位反馈；
- 1 tick/正常/3 tick 成本边界；
- vendor-open 与 next-close 的方向一致性；
- 保证金供应商/fallback 占比和 1.00/1.25/1.50 影子利用率；
- R 路径旧费与修正费的冻结订单会计桥接。

只有 P0/P1/P2 在全样本与验证期的关键结论方向一致、S/C 不导致策略排序根本反转，才能说“在预注册日线代理范围内具有初步稳健性”。如果上下界足以改变结论，必须写“日线数据不足以判断”。

## 15. 输出要求

至少生成：

```text
V6_1_MACHINE_REGISTRY.yaml
V6_1_EXPERIMENT_REGISTRY.md
configs/five_sector_momentum_v6_1.yaml
V6_1_PREFLIGHT_EVIDENCE_REPORT.md
V6_1_ENGINE_AUDIT.md
V6_1_BACKTEST_RESULT_REPORT.md
V6_1_FINAL_STATUS.json
V6_1_BLOCKER_REPORT.md（若触发）
scenario_parameters.csv/.pkl
scenario_metrics.csv/.pkl
annual_metrics.csv/.pkl
sector_contribution.csv/.pkl
instrument_contribution.csv/.pkl
long_short_contribution.csv/.pkl
cost_attribution.csv/.pkl
orders.csv/.pkl
fills.csv/.pkl
positions.csv/.pkl
daily_equity.csv/.pkl
rejections.csv/.pkl
one_price_order_events.csv/.pkl
one_price_full_market_diagnostics.csv/.pkl
challenge_set_replay.csv/.pkl
margin_source_coverage.csv/.pkl
margin_shadow_diagnostics.csv/.pkl
fee_compatibility_bridge.csv/.pkl
accounting_reconciliation.csv/.pkl
causal_prefix_checks.csv/.pkl
attempt_ledger_snapshot.csv/.pkl
test_results.csv/.pkl
modified_files.csv/.pkl
manifest.json
```

每张报告表必须指向底层文件。所有输入、配置、计划、代码、规则表和输出使用 canonical 内容哈希。日志和 manifest 必须通过秘密扫描。

## 16. 停止条件

遇到以下任一情况立即停止，不继续后续场景：

- 网络证据仍被 transport 错误污染；
- 无法冻结唯一机器注册表；
- 旧 pickle 无法在兼容环境读取；
- R01/R02 关键复现差异无法解释；
- 信号、目标或订单形成存在未来函数；
- 一价日代理越出真实订单作用域；
- 费用单位、T 特例、跨零或换月双边不正确；
- 滑点或费用重复扣除；
- next-close 获得执行当日不应有的收益；
- 账户勾稽失败；
- `equity<=0` 后继续生成合成收益；
- attempt 超出 16；
- 泄露 token 或修改受保护旧版本文件。

## 17. 本轮明确不做

- 不运行 v6 A01 或 v6 的 44 场；
- 不构造或声称官方历史限价；
- 不把 AkShare 近期分钟数据外推为全历史；
- 不新增信号周期、权重、品种或频率；
- 不优化一价日规则、滑点、buffer 或保证金；
- 不运行完整参数笛卡尔积；
- 不做 v5 或其他研究；
- 不把 v6.1 自动升级成正式可交易结论。

## 18. 最终汇报必须回答

1. 干净重跑后，三个 Tushare 端点分别是应用层无权限、静默空表、网络错误还是正常数据？
2. 供应商逐日保证金的真实覆盖是多少，fallback 实际占比是多少？
3. P0/P1/P2 是否给出方向一致的策略结论，区间有多宽？
4. P1 的改善有多少来自机械拒绝极端负成交，而非策略本身？
5. 修正费用后，v3 与袖套的相对关系是否变化？
6. 1 tick、正常、3 tick 成本下结论是否稳定？
7. vendor-open 与 next-close 是否导致策略排序反转？
8. 20skip5/250 袖套是否改善年份集中、最大回撤和 FG 依赖？
9. 哪些结论在日线数据下仍可信，哪些必须等待 `ft_limit`/分钟/盘口数据？
10. 是否值得购买或升级数据权限后返回 v6 正式路径？
