# v6 规范数据、交易日历与时点契约

## 1. 数据目标

v6 不直接改写 `data/normalized_v2` 或 `data/v3`。它建立一个带快照、来源和 as-of 信息的新数据层，使以下问题可以逐行回答：

- 这个数来自哪个端点、公告或代理规则？
- 在订单形成/执行时，它是否已经可得？
- 单位是什么，经过了什么归一化？
- 如果缺失，使用了什么回退，是否影响实际持仓或订单？
- 追加未来数据后，过去结果是否保持不变？

建议目录：

```text
data/v6/
  raw/<snapshot_id>/
  rules/<snapshot_id>/
  normalized/<snapshot_id>/
  manifests/<snapshot_id>/
```

每个快照只写一次。修订必须创建新 `snapshot_id`，不能覆盖。

### 1.1 Phase 1A：先验数据可行性止损

在编写 corrected 策略/账户路径之前，只允许先实现只读下载探针、规则表构建器和覆盖审计器，并依次回答：

1. 当前凭证对 `ft_limit` 是否真有逐合约历史权限；
2. 2015—2020 的 SHFE/INE 保证金能否由官方逐日值或带发布日期的官方规则完整推导；
3. Tushare 日线 `open` 对夜盘/非夜盘品种分别代表哪个 session；
4. 冻结 A01/A04 订单与持仓键能否达到 G0-DATA-FEASIBILITY 的正式覆盖阈值。

`ft_limit` 权限探针固定抽取 SHFE、INE、DCE、CZCE、CFFEX 各 2 个“历史已到期/研究期仍活跃”真实合约，共 10 个，并保存请求、返回行数、字段和权限错误；它只判断能力，不代替随后对全部实际订单键的 100% 覆盖。若权限不足，先尝试官方规则推导；升级数据权限或购买第二供应商属于新的外部授权，计划只能在 blocker 中建议，不能自动购买或用未经批准的数据替换。

若早期保证金官方/推导覆盖不达 G5：先在不看新绩效的 Phase 1 补建带 `published_at/known_time` 的官方规则；仍不达标则立即输出 `V6_BLOCKER_REPORT.md`，不启动 A01，不把 44 场自动降级后继续。可选的“全案 PROVISIONAL”或“仅费用修正 v6a”必须由用户另行授权并重新注册，不能在本计划内临时切换。

为保证 A→B 是真正单因素，v6 的行情 OHLC、settlement、volume、OI、合约元数据、主力映射和 Panama 共同字段必须从冻结的历史正式快照逐键复制，并与其 `legacy_market_payload_hash` 完全一致；v6 只新增日历标记、手续费、限价、保证金、单位和来源表。若数据审计发现必须修正任何历史行情或映射值，本 v1.4 注册立即停止，另建“数据纠错桥接”修订版后再运行，不能把行情变化混入手续费阶梯。

## 2. 规范表和主键

| 表 | 主键 | 关键字段 |
|---|---|---|
| `exchange_calendar` | `exchange,date` | `is_open,is_completed_week,is_completed_month,source,asof_time` |
| `contract_master` | `ts_code` | `instrument,exchange,list_date,delist_date,source` |
| `contract_specs` | `ts_code,effective_from` | `effective_to,multiplier,tick_size,priority,source`；若合约内规则不变也必须显式断言 |
| `daily_bars` | `ts_code,date` | `open,high,low,close,settlement,pre_settlement,volume,oi` |
| `main_mapping` | `instrument,date` | `ts_code,decision_source,decision_asof,roll_reason` |
| `fee_rules` | `rule_id` | `contract_scope,instrument_scope,effective_from,effective_to,trade_type,priority,fee_per_lot,fee_rate,rate_unit,customer_multiplier,source,is_proxy` |
| `margin_rules` | `ts_code,effective_from,side` | `effective_to,exchange_rate,customer_rate,unit,known_time,source,is_proxy` |
| `limit_rules` | `ts_code,date` | `upper_limit,lower_limit,rule_id,rounding_method,source_type,known_before_open,is_proxy` |
| `continuous_points` | `instrument,date` | `unadjusted_close,panama_close,point_change,active_contract,roll_gap` |
| `data_quality_events` | `event_id` | `dataset,key,severity,reason,resolution` |

所有日期统一为无时区的交易日键；所有时间字段用 ISO-8601 并带 `Asia/Shanghai` 时区。DataFrame 写盘前按主键稳定排序。

跨环境内容哈希不得直接使用 pickle 字节或 pandas 内部序列化。`table_content_hash` 固定采用 `canonical_json_rows_v1`：先写含列名、逻辑类型、主键和 schema 版本的头记录，再按主键稳定排序逐行编码；UTF-8、LF、JSON 键排序、无多余空白，日期/时间为 ISO-8601，布尔/整数保型，缺失为 JSON null，float64 以 IEEE-754 大端 16 进制位模式表示。禁止 NaN payload、对象 repr 和本地时区隐式转换。原始文件仍各自保存文件 SHA256，但跨版本“内容相同”只比较该规范内容哈希。

## 3. 来源优先级

### 3.1 行情和合约元数据

1. Tushare 合约日线及合约基础信息；
2. 交易所官方日线/合约资料作抽验；
3. 第二数据源只作交叉核对，不可在无记录情况下混填。

同一主键来源冲突时不自动取最后一条。保留冲突记录，按预注册优先级选择，并在 manifest 写明差异。手续费重叠时固定优先级为：精确真实合约规则高于品种通配规则；同层级官方临时公告高于常规表；再按更窄有效区间；仍有两个有效候选即硬失败，不能靠行序决定。

### 3.2 手续费

1. 交易所官方带生效日期公告或收费表；
2. Tushare `fut_settle` 的逐合约历史字段，经已核验单位映射；
3. 相邻时期/同类合约代理，只能在缺失时使用并明确 `is_proxy=true`。

手续费表必须区分 `OPEN`、`CLOSE_YESTERDAY`、`CLOSE_TODAY`。规则生效日期不能用全样本最后费率回填历史而不标记。

正式晋升还要求：按 B07 与 B08 实际成交分别计算 `proxy_commission/total_commission` 和 `proxy_turnover/total_turnover`，两者均≤20%，且任一完整年份的代理手续费占比≤50%；否则运行只能标为 `PROVISIONAL`。无论占比多少，H01/H02 代理规则×2压力必须保留。

### 3.3 保证金

1. Tushare 或交易所逐合约、逐日的多空最低保证金率；
2. 官方生效规则推导；
3. v3 静态率作为缺失代理回退；不得把它描述为所有日期的保守下界。

交易所最低率与客户实际率分开保存。v6 研究基准使用预注册客户代理：`客户率 = 交易所逐日率 × 1.25`；这是研究代理，不得称为实际期货公司账单。静态回退表存的是**交易所层代理率**，进入账户时同样且只乘一次 1.25，严禁把已经是客户率的值再次乘 1.25。

每条 margin rule 必须带 `published_at/known_time`。开盘前风控只允许使用执行时刻之前已公布的规则；交易日 t 收盘后发布、次日才生效的行不能回写 t 开盘。夜盘按交易所定义的“交易日”归属，晚间时段属于下一交易日时，所有费率、限价、成交和结算键也归到该下一交易日。

本项目 `next_open` 固定解释为 **Tushare `fut_daily.open` 所代表的该交易日首个交易 session 开盘**，不是未经验证的“次日日盘 9 点开盘”。有夜盘的商品通常可能对应前一民事日晚间，T 等无夜盘品种对应次日日间。G0 的阻断性核验固定为 RB、SC、M、TA、T 各 15 个日期，共 75 个“日线 open—分钟首开—交易日归属”观察对；每组覆盖普通周、节假日前后和至少一个实际订单日，日期按种子 20260905 从可取得的共同分钟区间稳定抽取，不因结果替换样本。分钟源优先交易所/供应商原始数据，可用独立第二源交叉核对，但必须记录口径。任一品种匹配率低于 100% 或历史分钟不可支持该定义时，当前计划停止并新增执行价格数据桥接，不能在兼容复现时静默替换。

### 3.4 涨跌停价

正式执行允许的来源只有：

1. `OFFICIAL_DAILY`：交易所/Tushare 逐合约逐日上下限；
2. `OFFICIAL_RULE_DERIVED`：用执行日前已知的前结算价、当时生效的官方幅度、最小价位和特殊规则因果推导。

`high==low`、收盘价或当日结算价只能产生 `DIAGNOSTIC_PROXY`，用于识别一字行情和做敏感性诊断，不能被描述为官方限价，也不能用于生成 t+1 开盘前才“知道”的限价。

`OFFICIAL_RULE_DERIVED` 必须把下列内容写进有效期规则，而不是用一个统一百分比：一般涨跌停幅度、连续停板扩大、节假日前后调整、新上市、交割月/临近交割、交易所临时公告、合约特殊参数和价格舍入。优先级固定为：官方逐日值 > 合约/日期临时公告 > 连续停板及交割特殊规则 > 一般品种规则。每条规则必须记录上下限分别如何按 tick 舍入；交易所方法无法确认时，该行只能标代理，不能晋升正式限价。

全历史 OHLC 只作为推导规则的**必要条件 oracle**：对每个有交易的合约日，必须满足 `derived_upper_ticks >= observed_high_ticks`、`derived_lower_ticks <= observed_low_ticks`，上下限自身位于 tick 网格；任何越界都 hard fail 或进入事前定义的官方数据更正例外表。满足该条件不证明规则正确。`high==low` 也不是限价真值：把审计发现的主力映射 12 日、对应 7 段成交/4 段逆向成交，以及 2025-04-07 RU2505 换月旧腿放入 `limit_challenge_set`，逐点寻找官方/因果规则来源；只有经来源确认、当日确有本策略逆向订单的点才断言 `REJECTED_LIMIT`。不得把“12 天”硬编码为正式全历史锁板数量，也不得要求所有低成交的一价日必等于涨跌停价。

## 4. 端点下载规则

`fut_settle`、`ft_limit` 必须逐合约查询。每次请求记录：

- endpoint、合约、起止日期、请求时间；
- 返回行数、字段、重复键、最早/最晚日期；
- 重试次数、异常、空返回原因；
- token 权限错误和速率限制；
- 原始响应文件 SHA256。

以下情况不是“可忽略 warning”，而是数据闸门失败：

- 预期上市区间内 0 行且没有明确的 `not_listed/no_permission` 分类；
- 必需字段整体为空；
- 同一主键存在冲突值；
- 请求被拒绝却写成成功；
- 关键订单涉及的日期最终没有可接受来源。

若 `ft_limit` 权限不可用，必须转入官方规则推导流程；不能仅把批量改成单合约就宣称问题解决。

## 5. 单位归一化

### 5.1 禁止全局猜测

建立 `field_unit_registry.csv`，至少包含：

```text
endpoint,field,exchange,instrument_scope,effective_from,
raw_unit,normalized_unit,transform,source,verified_example
```

已知重点：

- 比例手续费字段按千分数解释时转成十进制应除以 1000；
- T 的固定每手费曾落在比例字段，必须走专用固定费规则；
- T 保证金原值如 2.0 表示 2%，应按登记单位转为 0.02；不能只靠 `value > 1` 的临时启发式。

归一化后做合理区间检查，但区间检查不能代替单位来源。

### 5.2 价格和数量

- 原始价格必须大于 0；
- 成交价必须落在最小变动价位网格上；
- 手数必须为整数；
- 成交量、持仓量不得为负；
- multiplier、tick_size 随合约规则变化时按生效日处理。

## 6. 独立交易所日历

v6 继承 v4.2 修复原则：周信号日由独立交易所开市日历决定，而不是把当前行情文件的最后一行当作周末。

每个信号周期必须同时满足：

1. 该交易日是对应交易所该自然周/周期中已知的最后开市日；
2. 周期在当前数据截点已经完整；
3. 追加未来数据不会改变过去 `is_completed_week`；
4. 跨交易所节假日不以单一品种缺价代替市场休市；
5. 尚未完成的最后一周、最后一月显式标记，不生成信号。

日历至少与第二来源做全区间集合比较，输出缺失、额外、连续休市和临时休市差异。既有 Tushare/Sina 2014—2026 3161 个开市日一致可作锚点，但 v6 仍需对新快照重算。

跨交易所横截面使用一个组合级 `portfolio_week_completion_time`：取当周所有仍有合格候选的相关交易所各自最后开市会话结束时间的最大值，只有这些会话均结束后才排名。每个品种使用其交易所截至该时点的最后可得收盘，记录 `data_age_sessions`；若落后超过 1 个本品种交易会话则该周不合格。各真实合约的订单在其交易所下一次开市时执行。该规则必须在历史共同日历上复现 v4.2；若发现会改变 v4.2 历史信号，当前 v1.4 停止并增加显式日历桥接，不能静默混入 B02。

## 7. 主力映射和换月

映射规则继承 v3/v4.2，但字段时点必须明确：

- t 日收盘后可得的厂商主力映射只影响 t+1 目标；
- 到期最晚换月和 OI 回退只能使用 t 日及以前信息；
- OI 回退的确认天数、切换比和禁止倒退参数从 resolved config 读取；
- 每次映射变化记录旧合约、新合约、原因和决策时间；
- 实际换月需同时检查旧腿和新腿各自的限价、流动性、保证金和成交。

`FORWARD_CONTRACT` 等包含未来换月身份的字段只允许存在于报告域，不能被信号、风险、目标或执行模块导入。

## 8. Panama 连续点差序列

规范公式：

```text
roll_gap_t = new_contract_price_asof_(t-1 or earlier)
             - old_contract_price_asof_(t-1 or earlier)

panama_price_history_before_t += roll_gap_t
```

手算锚点：旧合约 100、新合约 110 时，gap=+10，换月前历史 100 加 10 后与新合约 110 对齐；旧合约 110、新合约 100 时，gap=-10，换月前历史 110 减 10 后与新合约 100 对齐。两个方向都必须进入单元测试。

允许在换月前最多 10 个交易日向后查找两合约共同价格；禁止使用 t 之后的价格。必须测试：

- 追加未来行情不改变历史 Panama 值；
- 换月日及前后点差手算正确；
- 缺少共同价格时不凭未来数据补齐；
- 连续价只用于 forecast 和点差波动率；
- 真实合约价用于订单、盈亏、成本、保证金和名义敞口。

`panama_close` 数据类型标记为 `CONTINUOUS_POINT_SERIES`。对它调用 `pct_change`、对数收益或百分比回撤必须抛错或在静态检查中失败。

## 9. 覆盖率验收

| 数据 | 强制要求 |
|---|---|
| 交易日历 | 研究区间每个交易所 100% 有开/闭市状态；未完成周期明确标记 |
| 主力映射 | 每个可交易品种每个策略日都有映射或明确 `not_listed/ineligible` |
| 映射合约行情 | 所有映射日 100% 有必需 OHLC/settlement；缺失即停止 |
| 手续费 | 所有潜在成交 100% 可命中规则；B07/B08 的代理手续费占比和代理成交名义占比均≤20%，任一完整年代理手续费占比≤50% |
| 限价 | 所有订单日 100% 有 `OFFICIAL_DAILY` 或 `OFFICIAL_RULE_DERIVED`；否则正式锁板结论停止 |
| 保证金 | 所有持仓/拟成交日 100% 有客户率或显式静态回退；官方/推导覆盖的绝对名义敞口权重在全组合、商品合计、T 合计各≥95%；有暴露的品种年度≥80%；关键临时提保暴露日=100% |
| 合约元数据 | 所有成交合约 100% 有 multiplier、tick_size、上市/到期日 |

保证金覆盖权重固定定义为：对场景全部持仓日，分子为使用 `OFFICIAL_DAILY/OFFICIAL_RULE_DERIVED` 率的 `Σ abs(lots)×settlement×multiplier`，分母为全部非零持仓的同一绝对名义敞口。G0 数据可行性先用 A01 与 A04 冻结持仓估计，G5 再用 B07/B08 实际持仓确认；全组合、商品合计或 T 合计任一低于 95%，或任一有非零敞口的 `instrument×完整自然年` 低于 80%，只能产生 `PROVISIONAL` 敏感性结果，不能晋升正式 v6 基准。交易所已知临时提保、节假日或交割特殊保证金生效日，只要存在实际持仓/拟成交，官方/推导覆盖必须为 100%。静态回退本身不进入分子。

## 10. 数据质量报告

必须输出：

- 按品种、合约、年份的数据覆盖；
- 上市前无数据、停牌/休市、退市后无数据的分类；
- 重复、非正价格、异常跳变、结算缺失；
- 映射与最大 OI 合约一致率及差异原因；
- 官方手续费/保证金/限价覆盖率与代理占比；
- 关键成交日数据来源清单；
- 至少 40 个跨品种/年份随机行情点的同源重拉，至少 20 个关键点的官方或第二来源抽验；
- RU2505 2025-04-07 及已识别锁板形态日的逐项人工核验；
- 输入文件、规则表、归一化表和日历哈希。

同源重拉只能证明下载/存储保真，不能被表述为独立供应商价格验证。

## 11. 安全和隐私

manifest 只记录 token 指纹，不能复制明文 token。报告、日志、异常堆栈和可分享底层结果均不得包含认证信息。
