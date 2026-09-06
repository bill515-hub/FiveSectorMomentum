# v6 账户勾稽、事件追踪与成本隔离规范

## 1. 账户核心原则

连续 Panama 价格从不进入账户。账户只使用实际真实合约的成交价、结算价、乘数、持仓和费用。

每日恒等式：

```text
equity_t = equity_(t-1)
         + gross_contract_pnl_t
         - commission_t
```

其中滑点已经通过成交价改变 `gross_contract_pnl_t`，不再作为第二笔现金扣款。保证金只形成占用和约束，不改变权益。

## 2. 事件级主键

每个真实事件至少包含：

```text
run_id, scenario_id, economic_strategy_key,
run_event_id, parent_run_event_id,
business_event_key, parent_business_event_key,
strategy_id, sleeve_id, sector, instrument, ts_code,
decision_date, created_time, effective_time, event_time,
event_class, event_status, reason_code, side, leg_role,
logical_event_slot, lots, price,
source_rule_id, data_snapshot_id
```

虚拟内部目标也有事件，但必须 `is_real_order=false`、`cash_effect=0`。

`run_event_id` 可以包含运行身份；`business_event_key` 必须在首次运行前按以下规则冻结并跨进程稳定：

```text
business_event_key = SHA256(canonical_json({
  economic_strategy_key, strategy_id, sleeve_id,
  decision_date, effective_time, event_class, logical_stage,
  sector, instrument, ts_code, side, leg_role,
  parent_business_event_key, logical_event_slot
}))
```

`canonical_json` 固定 UTF-8、键排序、ISO-8601 时间和显式 null。`event_class` 表示稳定阶段（如 SIGNAL/TARGET/ORDER/EXECUTION/SETTLEMENT/FEE/MARGIN），成交或拒单放在待比较的 `event_status`，不进入键。`logical_event_slot` 在生成业务意图时先按 `(logical_stage,leg_role,sector,instrument,ts_code,side,effective_time)` 稳定排序，再在同一父事件内从 0 编号；真正完全相同的多腿意图由上游稳定 `intent_slot` 打破并列，禁止使用 DataFrame 行号、运行时 UUID 或哈希迭代顺序。

键中明确禁止包含 `run_id,scenario_id,attempt_id,output_path`，也禁止包含待比较的 `lots,price,event_status,commission,slippage,margin,pnl,equity`。每个场景内 `business_event_key` 必须唯一；B07↔I01、B08↔I02 的键集合必须相同，再按键比较所有 payload。左右缺键和同键值差均为确定性失败，不能只取交集。

## 3. 订单生命周期

```text
CREATED
  ├─ FILLED
  ├─ PARTIALLY_FILLED → FILLED / EXPIRED_UNFILLED / REJECTED_*
  ├─ REJECTED_LIMIT
  ├─ REJECTED_MARGIN
  ├─ REJECTED_VOLUME
  ├─ CANCELLED_RECALCULATE
  └─ EXPIRED_POLICY
```

每个订单总量必须满足：

```text
ordered_lots = filled_lots + terminal_unfilled_lots + open_lots
```

其中每一单位 `terminal_unfilled_lots` 只能归入 `REJECTED_*`、`CANCELLED_RECALCULATE` 或 `EXPIRED_*` 中的一个终态，不能重复计数。L0 的逆限价量以 `REJECTED_LIMIT` 终结，次日是新订单，不再把同一量记一次取消。参与率部分成交的剩余量以 `EXPIRED_UNFILLED` 终结；只有仍处于 open 状态且被新目标替代的普通旧单才可使用 `CANCELLED_RECALCULATE`。日终正式模式不允许无原因的 `open_lots`；顺延订单必须有前一日父订单和剩余重试次数。

## 4. 逐合约盈亏

账本应按**互斥数量**做期货逐日盯市，任何一手只能落入一类：

- 未平的昨仓：前结算→当日结算；
- 当日已平的昨仓：前结算→平仓成交价；
- 当日新开且留仓：开仓成交价→当日结算；
- 当日新开又平仓：平仓成交价−开仓成交价；
- 换月旧/新合约分别计算；
- 方向和手数均以真实事件为准。

无论内部实现采用哪种等价公式，必须由独立逐合约重放得到同一 `gross_contract_pnl_t`。

## 5. 手续费恒等式

```text
commission_total
= commission_open
 + commission_close_yesterday
 + commission_close_today
```

并同时满足：

```text
commission_total
= sum_by_fill
= sum_by_contract
= sum_by_instrument
= sum_by_sector
= sum_by_year
```

跨零和换月的每腿必须能追溯到具体 FeeRule。拒单、过期和取消事件手续费为零。

## 6. 滑点恒等式

每笔成交：

```text
requested_ticks
= base_ticks + roll_extra_ticks + impact_ticks

executed_ticks
= abs(fill_price - reference_open) / tick_size

slippage_cost_total
= abs(lots) * abs(fill_price - reference_open) * multiplier
```

金额归因固定为：

```text
executed_slippage_cost
= requested_base_cost
 + requested_roll_cost
 + requested_impact_cost
 + grid_rounding_cost
 - limit_clip_reduction
```

所有字段同时保留 `requested_ticks,executed_ticks,limit_clip_ticks,grid_rounding_ticks`。价格网格差额唯一进入 `grid_rounding_cost`，限价截断未实现的 requested tick 唯一进入 `limit_clip_reduction`，不按结果选择其他归属。无成交订单全部滑点字段为 0。

## 7. 组合贡献恒等式

```text
gross_pnl_total = Σ instrument_gross_pnl
commission_total = Σ instrument_commission
net_pnl_total = Σ instrument_net_pnl

net_pnl_total
= Σ sector_net_pnl
= Σ long_short_net_pnl
= equity_end - initial_capital
```

贡献表必须基于真实合约事件映射回品种和板块，不能用当期连续合约身份近似历史归属。

## 8. 袖套内部目标与真实订单

完整链：

```text
sleeve_raw_target
→ sleeve_risk_target
→ sum_by_real_contract
→ preliminary_liquidity_and_oi_capped_target
→ portfolio_and_realized_vol_scaled_target
→ normal_buffered_target
→ final_liquidity_oi_margin_leverage_constrained_target
→ real_order = final_liquidity_oi_margin_leverage_constrained_target - actual_position
```

强制检查：

- 所有袖套内部目标之和等于合约层净额前目标；
- 同一真实合约反向袖套先净额，不产生虚拟成交；
- 缩放前流动性/OI 预限额保留既有行为；B07/B08 在其基础上只新增缩放与 buffer 后的同阈值最终复检；
- buffer 只比较组合缩放后的最终净目标和实际持仓一次；
- 最终成交量/OI、保证金和杠杆硬约束在正常 buffer 后覆盖，目标硬约束降险、清仓、换月和 120% 紧急减仓不受 buffer 阻止；这不构成经纪商强平模型；
- 硬约束后的最终目标必须满足 `abs(lots)<=floor(20日成交量中位数*5%)` 和 `abs(lots)<=floor(20日持仓量中位数*1%)`，且其后不得再有仓位放大；
- `fills` 中每一笔都必须有真实订单父事件；
- `commission/slippage/impact` 中不得出现内部 sleeve target ID 作为收费对象；
- 无信号预算在各层都保持未使用。

## 9. 保证金勾稽

预交易检查和日终占用分开：

```text
pretrade_margin_required
= abs(projected_position_lots)
 * executable_order_price
 * multiplier
 * customer_margin_rate_known_at_execution

eod_margin_used
= abs(eod_position_lots)
 * settlement_price
 * multiplier
 * customer_margin_rate_effective_at_eod
```

预交易率和价格不得来自执行日收盘后数据。夜盘按照交易所定义的下一交易日键归属。需同时汇总：商品保证金、T 保证金、总保证金、权益占比、约束前后差和回退来源。多空保证金率不同时，不能用两者最大值代替方向值，除非某个单独压力情景明确这样定义。

日终超过 65%/78% 时，账本只记录真实持仓占用、超限幅度和下一目标计算中的 `MARGIN_TARGET_REDUCTION`；不得生成独立强平成交。若 `equity<=0`，写入 `ACCOUNT_INSOLVENT` 并在触发点终止场景；截至触发点的实际现金、持仓、负债和成本仍须勾稽，触发后的行不得生成。禁止外部注资，也禁止用合成有限责任权益替换真实账本。

## 10. 可加性成本与非加性路径反事实

### 10.1 手续费和可行的冻结成交滑点

只有能在相同 fills/数量上重新计价的项目使用三套结果：

1. `old_dynamic`：上一级完整动态运行；
2. `new_cost_on_old_path`：冻结旧 fills/positions，仅重算费用或可行的成交价；
3. `new_dynamic`：新规则完整重跑。

```text
direct_accounting_effect
= new_cost_on_old_path - old_dynamic

path_feedback_effect
= new_dynamic - new_cost_on_old_path

total_effect
= new_dynamic - old_dynamic
             = direct_accounting_effect + path_feedback_effect
```

这里没有可自由解释的“交互残差”；等式残差只能是≤0.01元的数值勾稽误差。若滑点重定价会越过限价，该笔不满足冻结路径可加条件，必须转入非加性诊断。

### 10.2 限价和保证金

限价改变是否成交，保证金改变可成交数量，因此不能把旧 fills 当作合法的直接会计反事实：

- 限价：对冻结 `order_intents` 输出机械的可成交/拒绝差，再比较完整动态路径；
- 保证金：对冻结 positions/targets 重算占用和会触发的约束，再比较完整动态路径；
- 两者只报告相邻完整运行的总路径差、首个分歧事件和后续传播，不称“直接成本+反馈”的精确分解；
- 事后删除成交只能作诊断，不能形成正式权益。

## 11. 独立勾稽输出

每个场景至少生成：

- `accounting_reconciliation.csv/.pkl`；
- `event_ledger.csv/.pkl`；
- `position_replay.csv/.pkl`；
- `fee_recalculation.csv/.pkl`；
- `slippage_reconciliation.csv/.pkl`；
- `margin_reconciliation.csv/.pkl`；
- `contribution_reconciliation.csv/.pkl`；
- `internal_vs_real_cost_check.csv/.pkl`；
- `path_feedback_decomposition.csv/.pkl`。

每张表包含 `expected,actual,residual,tolerance,status`。禁止只写“通过”而不保留数字。

## 12. 原因码

订单和目标至少使用稳定原因码：

```text
SIGNAL_ENTRY
SIGNAL_EXIT
CROSS_ZERO_REVERSAL
CROSS_SECTION_SWITCH
VOL_TARGET_RESIZE
EMERGENCY_VOL_REDUCTION
MARGIN_TARGET_REDUCTION
MAIN_CONTRACT_ROLL
BUFFER_BLOCKED
LIMIT_REJECTED
VOLUME_PARTIAL
DEFERRED_ONE_DAY
RUNNER_UP_SUBSTITUTION
TARGET_RECALCULATED
```

成本来源、换手来源和拒单来源均从原因码聚合，不能由结果后验猜测。

## 13. 审计容差与失败

- 手数、事件数、订单状态：必须完全相等；
- 单笔和逐日人民币：≤0.01 元；
- 全期人民币：≤0.01 元；
- 浮点信号：≤1e-12 或记录 ULP；
- 任一残差超限，`scenario_status=ACCOUNTING_FAILED`，顶层 `RUN_STATUS.status=FAILED_GATE, failed_gate_id=G6`，不能进入指标表；
- 不允许用四舍五入后的报告表反向做勾稽，必须用底层全精度数据。
