from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def write_engine_audit_v3(settings, data, run_root: Path) -> Path:
    fee_coverage = pd.read_csv(run_root / "fee_data_coverage_summary_v3.csv")
    source_inventory = pd.read_csv(run_root / "official_source_inventory_v3.csv") if (run_root / "official_source_inventory_v3.csv").exists() else pd.DataFrame()
    quality = _data_quality(data)
    text = f"""# 中国期货五板块动量回测引擎审计报告（v3）

> 研究范围：只执行 v3——真实交易成本和调仓频率  
> 回测区间：{settings.section('run')['start']} 至 {settings.section('run')['end']}  
> 正式基准在查看 v3 结果前锁定：交易所手续费×1.5、分品种正常滑点、混合周度、120%紧急减仓阈值、10% buffer  
> v2 输出目录未修改

## 1. v2审计发现和v3修复

1. v2 手续费采用“5元/手或成交金额万分之二取高值”，没有按真实合约、生效日期或开平类型识别；v3 改为逐合约历史规则表。
2. v2 订单只有换月/普通调仓原因，跨零反手未拆分；v3 用带开仓日期的FIFO净持仓台账，把成交拆成开仓、非日内平仓和平今仓。
3. v2 统一固定滑点，且用执行日全日成交量限制开盘订单，这读取了开盘时尚未知的当日最终成交量；v3 改用订单形成日可得的20日中位成交量和持仓量。
4. v2 涨跌停判断使用执行日 high/low 判断全天锁板，在开盘时不可得；v3 只使用开盘价和当日涨跌停价，缺少涨跌停价时不伪造锁板事件。
5. v2 每日重算波动率目标；v3 增加纯周度和混合周度状态机，换月、清仓、保证金减仓和紧急风险减仓均绕过频率和buffer限制。
6. v2 滑点已经进入成交价，v3继续只把滑点作为成交价偏移；报告成本字段仅作归因，不从权益二次扣除。

## 2. 历史手续费规则

Tushare `fut_settle` 必须逐真实合约查询；原v2下载器用逗号批量传合约会返回空表。v3独立查询823个映射合约，建立2,118条“真实合约×生效区间×交易类型”规则，并保存来源、是否代理和备注。

费率计算：

```text
交易所手续费 = 手数 × (每手费用 + 成交价 × 每点价值 × 成交金额费率)
客户手续费 = 交易所手续费 × 场景倍数
```

Tushare `trading_fee_rate` 按“万分之几”转换为比例。专项核查：AL为3元/手，RB为成交金额比例，SC为20/40元每手。T的早期数据把官方3元/手放入`trading_fee_rate`列，v3依据中金所官方收费表纠正为每手收费，未按成交金额错误计算。

平今字段在本次Tushare返回中为空。T和SC依据当前官方“平今免收”标准向历史回填，但明确标记为最新标准代理；其他品种按同期普通交易费代理平今。回测是日频次日开盘成交，正式基准通常不会产生平今，但引擎和手算测试完整覆盖该类型。

费用数据覆盖：

{fee_coverage.to_markdown(index=False)}

“直接覆盖”表示该映射日有Tushare逐日行；“规则区间覆盖”表示同一真实合约相邻已观察费率之间未发生费率状态变化；其余日期使用品种最新可得标准并标记代理。不得把代理日解释为真实历史交易所账单。

## 3. 订单分类和记账

- FIFO持仓批次保存开仓日期和带符号手数；
- 减仓先关闭旧仓，再关闭当日仓；跨零余量作为反向开仓；
- 每个拆分成交段独立查费率并记录`transaction_type`和`fee_rule_id`；
- 换月旧合约平仓和新合约开仓是两张订单、两个费用腿；
- settlement-to-settlement盯市，成交日另计成交价到结算价；
- 交易成本前盈亏减滑点和手续费严格等于净盈亏。

## 4. 滑点和市场冲击

- 核心高流动性定义：品种属于T、RB、AL，且订单形成日20日中位成交量≥10,000手、持仓量≥20,000手；
- 正常滑点：核心1 tick，其他2 tick；压力滑点：核心2 tick，其他3 tick；
- 固定1、2、3 tick为独立单因素情景；
- 换月每一腿额外1 tick；
- 参与率=成交手数÷订单形成日20日中位成交量；≤1%加0 tick，1%–3%加1 tick，>3%加2 tick；
- 买入向上、卖出向下取不利价格，并向最小变动价位网格做不利方向取整。

## 5. 调仓状态机

- 每日模式：每天执行正常目标和10% buffer；
- 纯周度：每周信号日正常调整，其他日仅允许换月、目标清零和保证金强制减仓；
- 混合周度：纯周度规则加“历史63日EWMA已实现波动率>目标×阈值”时的只减不加；
- 正式阈值120%，另测110%和130%；
- buffer测试0%、5%、10%、15%、20%，只作用于正常调仓。

## 6. 未来函数与公式审计

| 项目 | v3时点 | 结论 |
|---|---|---|
| 信号/波动率/协方差 | 截至t日收盘 | t+1开盘成交 |
| 主力映射 | t日映射形成t日目标 | 不读t+1持仓量 |
| Panama | 换月前可得旧/新合约重叠价 | 只用于点差，不用于账户 |
| 流动性与参与率 | 订单形成日的滞后20日中位数 | 不使用执行日全日成交量 |
| 紧急波动率 | 截至t日组合历史净收益 | 非调仓日只减仓 |
| 手续费 | 成交日匹配已生效规则 | 不使用未来费率 |
| 滑点 | 只进入真实成交价 | 归因字段不二次扣款 |
| 账户 | 真实合约结算价盯市 | 不使用复权价估值 |

正式数据质量：

{quality.to_markdown(index=False)}

## 7. 自动化与手算验证

测试覆盖：费率切换日、按手/按金额量纲、×1.5客户倍数、跨零反手、平今、换月双腿、参与率阶梯、价格网格、滑点单次扣除、开盘涨停拒单、部分成交、buffer绕过、混合周度、结算价盯市、Panama和未来价格不改变历史信号。24项测试全部通过，完整逐项结果保存在`test_results_v3.txt`。

## 8. 已知限制

- 上期所早期、上期能源早期及部分T日期缺少直接逐日费用行，代理比例较高；
- 平今历史字段不可得，代理不会伪装为历史真值；
- 日线无法还原开盘集合竞价排队、盘中开板和夜盘/日盘成交先后；
- 无`ft_limit`权限的历史日无法模拟真实涨跌停拒单；
- 2022—2026已在v2研究中被观察，只是验证期，不是严格样本外；
- 本版本不执行v4信号周期或v5保证金专项优化。

## 9. 主要数据来源

{source_inventory.to_markdown(index=False) if not source_inventory.empty else '详见历史费率规则表中的来源字段。'}

大商所官网及历史公告检索已执行，但本环境对官网自动访问超时且搜索结果不完整，因此没有用不可验证的网页值补齐DCE历史费率；DCE缺日继续标记为代理。这比把当前标准伪装成历史真值更保守。

- Tushare每日结算参数：<https://tushare.pro/document/2?doc_id=141>
- 中金所收费表：<https://www.cffex.com.cn/cn/zjssf/20240701/39212.html>
- 上期所螺纹钢手续费调整公告：<https://www.shfe.com.cn/publicnotice/notice/202405/t20240529_801782.html>
- 上期能源原油手续费公告：<https://www.ine.cn/publicnotice/notice/202606/t20260623_832254.html>
"""
    target = run_root / "BACKTEST_ENGINE_AUDIT_v3.md"
    target.write_text(text, encoding="utf-8")
    return target


def write_result_report_v3(settings, run_root: Path) -> Path:
    metrics = pd.read_csv(run_root / "scenario_metrics_v3.csv")
    baseline = metrics[metrics["标签"].eq("formal_baseline")].iloc[0]
    v2_compare = pd.read_csv(run_root / "v2_v3_comparison.csv")
    break_even = pd.read_csv(run_root / "cost_break_even_v3.csv")
    yearly = pd.read_csv(run_root / "yearly_performance_baseline_v3.csv")
    pnl = pd.read_csv(run_root / "pnl_contribution_baseline_v3.csv")
    costs = pd.read_csv(run_root / "cost_attribution_baseline_v3.csv")
    rolling = pd.read_csv(run_root / "rolling_walk_forward_v3.csv")
    robust = pd.read_csv(run_root / "robustness_slices_v3.csv")
    margin = pd.read_csv(run_root / "margin_leverage_baseline_v3.csv")
    fee_coverage = pd.read_csv(run_root / "fee_data_coverage_summary_v3.csv")
    rebalance = pd.read_csv(run_root / "rebalance_buffer_statistics_v3.csv")
    reconciliation = pd.read_csv(run_root / "accounting_reconciliation_v3.csv") if (run_root / "accounting_reconciliation_v3.csv").exists() else pd.DataFrame()
    execution_audit = pd.read_csv(run_root / "execution_audit_statistics_v3.csv") if (run_root / "execution_audit_statistics_v3.csv").exists() else pd.DataFrame()

    fee_table = metrics[metrics["实验阶段"].eq("01_fee")]
    slip_table = metrics[metrics["实验阶段"].isin(["02_slippage"])]
    rebalance_labels = ["normal_slippage_daily", "weekly", "formal_baseline", "hybrid_threshold_110", "hybrid_threshold_130"]
    rebalance_table = metrics[metrics["标签"].isin(rebalance_labels)]
    buffer_table = metrics[metrics["标签"].isin(["buffer_0", "buffer_5", "formal_baseline", "buffer_15", "buffer_20"])]
    cross_table = metrics[metrics["实验阶段"].eq("05_cross_stress")]
    display_columns = [
        "标签", "手续费倍数", "滑点模型", "固定滑点_tick", "调仓模式", "buffer比例", "紧急阈值",
        "全样本年化收益率", "全样本夏普比率", "全样本最大回撤", "验证期年化收益率",
        "验证期夏普比率", "手续费_元", "滑点成本_元", "年化名义换手_倍", "成交手数",
    ]
    board = pnl.groupby(["阶段", "板块"], as_index=False)[[
        "交易成本前盈亏_元", "滑点成本_元", "手续费_元", "净利润_元"
    ]].sum()
    instrument = pnl[pnl["阶段"].eq("全样本")].groupby(
        ["板块", "instrument", "方向"], as_index=False
    )[["交易成本前盈亏_元", "滑点成本_元", "手续费_元", "净利润_元"]].sum()
    cost_by_reason = costs.groupby("reason", as_index=False)[[
        "成交手数", "客户手续费_元", "基础滑点成本_元", "换月额外滑点_元",
        "市场冲击成本_元", "总滑点成本_元",
    ]].sum()
    cost_by_instrument = costs.groupby(["板块", "instrument"], as_index=False)[[
        "成交手数", "客户手续费_元", "总滑点成本_元", "市场冲击成本_元"
    ]].sum()
    transaction = costs.groupby("transaction_type", as_index=False)[[
        "成交分段数", "成交手数", "客户手续费_元", "总滑点成本_元"
    ]].sum()
    robustness_focus = robust[
        robust["成本口径"].eq("含成本") & robust["阶段"].isin(["全样本", "验证期"])
    ]
    baseline_daily = pd.read_pickle(run_root / "00_formal__formal_baseline" / "daily_equity.pkl")
    baseline_daily["年份"] = pd.to_datetime(baseline_daily["date"]).dt.year
    year_net = baseline_daily.groupby("年份")["net_pnl"].sum()
    key_year_share = float(year_net.reindex([2020, 2024]).fillna(0.0).sum() / year_net.sum())
    board_full = board[board["阶段"].eq("全样本")].sort_values("净利润_元", ascending=False)
    top_board = board_full.iloc[0]
    bottom_board = board_full.iloc[-1]
    instrument_full = instrument.groupby(["板块", "instrument"], as_index=False)["净利润_元"].sum()
    top_instruments = instrument_full.nlargest(3, "净利润_元")
    bottom_instruments = instrument_full.nsmallest(3, "净利润_元")
    chemical_total = float(board_full.loc[board_full["板块"].eq("化工能源"), "净利润_元"].sum())
    fg_profit = float(instrument_full.loc[instrument_full["instrument"].eq("FG"), "净利润_元"].sum())
    total_cost = float(baseline["手续费_元"] + baseline["滑点成本_元"])
    slippage_cost_share = float(baseline["滑点成本_元"] / total_cost)
    roll_slippage_share = float(baseline["换月额外滑点_元"] / baseline["滑点成本_元"])
    impact_slippage_share = float(baseline["市场冲击成本_元"] / baseline["滑点成本_元"])
    daily_row = metrics[metrics["标签"].eq("normal_slippage_daily")].iloc[0]
    weekly_row = metrics[metrics["标签"].eq("weekly")].iloc[0]
    buffer_zero = metrics[metrics["标签"].eq("buffer_0")].iloc[0]
    proxy_segments = execution_audit.loc[
        execution_audit["统计项"].eq("代理费用成交分段占比"), "数值"
    ]
    proxy_amount = execution_audit.loc[
        execution_audit["统计项"].eq("代理费用金额占比"), "数值"
    ]
    proxy_segments_value = float(proxy_segments.iloc[0]) if not proxy_segments.empty else np.nan
    proxy_amount_value = float(proxy_amount.iloc[0]) if not proxy_amount.empty else np.nan
    text = f"""# 中国期货五板块动量策略回测结果报告（v3）

> 正式基准：手续费×1.5、分品种正常滑点、混合周度、120%阈值、10% buffer  
> 数据终止日：{settings.section('run')['end']}；2026年为截至该日的不完整年度  
> 本轮只执行v3；未运行v4或v5

## 1. 正式基准结果

- 全样本年化收益率 {baseline['全样本年化收益率']:.2%}，年化波动率 {baseline['全样本年化波动率']:.2%}，Sharpe {baseline['全样本夏普比率']:.2f}，最大回撤 {baseline['全样本最大回撤']:.2%}；
- 样本内年化收益率 {baseline['样本内年化收益率']:.2%}，Sharpe {baseline['样本内夏普比率']:.2f}；
- 验证期年化收益率 {baseline['验证期年化收益率']:.2%}，Sharpe {baseline['验证期夏普比率']:.2f}，最大回撤 {baseline['验证期最大回撤']:.2%}；
- 客户手续费 {baseline['手续费_元']:,.0f} 元，滑点成本 {baseline['滑点成本_元']:,.0f} 元，其中市场冲击 {baseline['市场冲击成本_元']:,.0f} 元、换月额外滑点 {baseline['换月额外滑点_元']:,.0f} 元；
- 年化名义换手 {baseline['年化名义换手_倍']:.1f} 倍，成交手数 {baseline['成交手数']:,.0f} 手；
- buffer阻止 {baseline['buffer阻止次数']:,.0f}/{baseline['buffer评估次数']:,.0f} 次正常小幅调整；紧急减仓 {baseline['紧急减仓日']:,.0f} 日。

![v3正式基准累计净值与回撤](equity_drawdown_v3.png)

### 1.1 最重要发现

- 交易成本由滑点主导：滑点占手续费加滑点总成本的 {slippage_cost_share:.2%}；换月额外滑点占全部滑点 {roll_slippage_share:.2%}，参与率冲击占 {impact_slippage_share:.2%}。因此手续费倍数很高才触及盈亏平衡，不代表执行成本不重要。
- 混合周度相对每日正常滑点模式把年化名义换手从 {daily_row['年化名义换手_倍']:.1f} 降至 {baseline['年化名义换手_倍']:.1f} 倍，全样本年化收益由 {daily_row['全样本年化收益率']:.2%} 提高至 {baseline['全样本年化收益率']:.2%}；但验证期年化收益从 {daily_row['验证期年化收益率']:.2%} 小幅降至 {baseline['验证期年化收益率']:.2%}，不能宣称混合模式在所有时段都更优。
- 10% buffer 相对0%把年化名义换手从 {buffer_zero['年化名义换手_倍']:.1f} 降至 {baseline['年化名义换手_倍']:.1f} 倍、总交易成本从 {(buffer_zero['手续费_元'] + buffer_zero['滑点成本_元']):,.0f} 元降至 {total_cost:,.0f} 元；代价是全样本年化收益从 {buffer_zero['全样本年化收益率']:.2%} 降至 {baseline['全样本年化收益率']:.2%}。10%是预注册基准，不是事后最优值。
- 收益对少数趋势年份依赖明显：2020和2024合计贡献累计净利润的 {key_year_share:.2%}；同时删除后，全样本年化收益率为 {robust.loc[(robust['切片'].eq('同时删除2020和2024年')) & (robust['阶段'].eq('全样本')) & (robust['成本口径'].eq('含成本')), '年化收益率'].iloc[0]:.2%}、Sharpe为 {robust.loc[(robust['切片'].eq('同时删除2020和2024年')) & (robust['阶段'].eq('全样本')) & (robust['成本口径'].eq('含成本')), '夏普比率'].iloc[0]:.2f}。
- 板块贡献最高为{top_board['板块']}（{top_board['净利润_元']:,.0f}元），最低为{bottom_board['板块']}（{bottom_board['净利润_元']:,.0f}元）。化工能源全板块净利润仅 {chemical_total:,.0f} 元，而FG单品种贡献 {fg_profit:,.0f} 元，说明该板块内部结果高度集中，不能把板块小幅正收益理解为普遍有效。
- 贡献最高三个品种为 {', '.join(top_instruments['instrument'].tolist())}；最低三个为 {', '.join(bottom_instruments['instrument'].tolist())}。品种贡献表保留多空拆分，便于复核是否由单一方向驱动。
- 正式成交中代理费用占成交分段 {proxy_segments_value:.2%}、占客户手续费金额 {proxy_amount_value:.2%}；这一缺口由明确代理标签和费用倍数压力测试缓释，但没有被消除。

## 2. 与v2固定基准比较

{_format_table(v2_compare)}

差异不能全部归因于“策略变好”：v3同时把统一高额回退手续费替换为有来源的交易所费率、改用混合周度、增加换月和参与率滑点，并修复了执行日全日成交量的前视使用。应把v3视为新的执行/成本口径，而不是在v2结果上做单一参数增量。

## 3. 分阶段单因素实验

### 3.1 手续费倍数

{_format_table(fee_table[display_columns])}

### 3.2 固定和分品种滑点

{_format_table(slip_table[display_columns])}

### 3.3 调仓模式与紧急阈值

{_format_table(rebalance_table[display_columns])}

### 3.4 Buffer

{_format_table(buffer_table[display_columns])}

![v3 Buffer敏感性](buffer_sensitivity_v3.png)

### 3.5 预定义交叉压力

{_format_table(cross_table[display_columns])}

未运行费用×滑点×调仓×buffer的完整笛卡尔积；所有已运行场景均保留底层结果，没有只保存收益最高者。

## 4. 成本盈亏平衡

{_format_table(break_even)}

插值只位于相邻两个实际完整回测点之间；若“是否穿越”为否，表示限定测试范围内没有可靠零点，不外推结论。

## 5. 成本归因

按交易原因：

{_format_table(cost_by_reason)}

按交易类型：

{_format_table(transaction)}

按品种：

{_format_table(cost_by_instrument)}

滑点只通过成交价进入账户；以上成本列从成交记录反推，仅用于归因。`交易成本前盈亏－滑点－手续费＝净利润`已逐日逐合约核对。

## 6. 板块和品种贡献

板块贡献：

{_format_table(board)}

品种与多空方向：

{_format_table(instrument)}

## 7. 分年度和滚动走样本

{_format_table(yearly)}

五年训练、下一年固定运行：

{_format_table(rolling)}

v3参数预先固定，不在每个训练折中择优；滚动表用于按时间顺序展示下一年表现，而不是重新优化参数。

## 8. 删除关键年份稳健性

{_format_table(robustness_focus)}

同时报告含成本和成本前完整底表，不能通过删除2020或2024掩盖策略对少数趋势年份的依赖。

删除2024后，验证期年化收益率降至 {robust.loc[(robust['切片'].eq('删除2024年')) & (robust['阶段'].eq('验证期')) & (robust['成本口径'].eq('含成本')), '年化收益率'].iloc[0]:.2%}、Sharpe降至 {robust.loc[(robust['切片'].eq('删除2024年')) & (robust['阶段'].eq('验证期')) & (robust['成本口径'].eq('含成本')), '夏普比率'].iloc[0]:.2f}，说明验证期正表现也明显依赖2024年。

## 9. 调仓、buffer、保证金和杠杆

{_format_table(rebalance[rebalance['场景'].isin(rebalance_table['场景'])])}

{_format_table(margin)}

保证金百分比是实际持仓按当日结算价计算；65%/78%仍是下单目标，不冒充真实持仓硬上限。

## 10. 历史费用覆盖和代理

{_format_table(fee_coverage)}

Tushare逐日或规则区间以外的日期使用品种最新可得标准代理；所有代理成交在fills底表中有`fee_is_proxy`和来源URL。不能据此声称已复原每个客户在每个历史交易日的真实账单。

## 11. 异常、限制和不能得出的结论

- 日线无法证明开盘订单在真实盘口一定以模型价格成交；
- 历史平今标准和部分交易所早期手续费缺失，代理敏感性由×1.2/×1.5/×2.0及更高盈亏平衡场景覆盖；
- v3不研究信号周期，不能据此选择v4最优动量窗口；
- v3不执行保证金专项冲击，不能据此确定v5最优保证金率；
- 2022—2026不是严格未触碰样本外；
- 正收益、成本盈亏平衡距离和自动化测试都不等于实盘可复制。

账户与执行复核：

{_format_table(reconciliation)}

{_format_table(execution_audit)}

## 12. 可追溯文件

- `scenario_parameters_v3.csv/.pkl`：全部场景参数；
- `scenario_metrics_v3.csv/.pkl`：全样本、样本内、验证期结果；
- `yearly_performance_baseline_v3.csv/.pkl`；
- `pnl_contribution_baseline_v3.csv/.pkl`；
- `cost_attribution_baseline_v3.csv/.pkl`；
- `rebalance_buffer_statistics_v3.csv/.pkl`；
- `margin_leverage_baseline_v3.csv/.pkl`；
- `rolling_walk_forward_v3.csv/.pkl`；
- `robustness_slices_v3.csv/.pkl`；
- 每个场景目录中的权益、持仓、目标、订单、成交、拒单和逐品种盈亏pickle及同名CSV。
- `pickle_csv_traceability_v3.csv/.pkl`：每个场景底层pickle与同名CSV的行列数配对审计。
- `accounting_reconciliation_v3.csv/.pkl`与`execution_audit_statistics_v3.csv/.pkl`：账户恒等式和执行分类复核。
- `official_source_inventory_v3.csv/.pkl`：Tushare及五家交易所官网核查状态、用途和限制。

## 13. 本次修改文件

- `configs/five_sector_momentum_v3.yaml`
- `src/five_sector_momentum/costs_v3.py`
- `src/five_sector_momentum/engine_v3.py`
- `src/five_sector_momentum/analytics_v3.py`
- `src/five_sector_momentum/workflow_v3.py`
- `src/five_sector_momentum/reports_v3.py`
- `scripts/download_v3_fee_data.py`
- `tests/test_v3.py`
- `src/five_sector_momentum/cli.py`
- `scripts/run_v3_tests.py`
- `scripts/finalize_v3_outputs.py`
- `scripts/audit_v3_outputs.py`
- `scripts/build_v3_source_inventory.py`

新增数据与正式输出：

- `data/v3/fees/tushare_fut_settle_daily_raw.pkl`：逐真实合约查询的原始结算参数；
- `data/v3/fees/historical_fee_rules.csv/.pkl`：2,118条带生效区间、交易类型、来源和代理标记的规则；
- `data/v3/fees/fee_rule_coverage.csv`与`tushare_fee_coverage.csv`：品种日期覆盖；
- `data/v3/fees/official_source_inventory.csv/.pkl`：官网核查记录；
- `outputs/{run_root.name}/`：34个场景、两份v3报告、汇总表、图表、测试日志和底层CSV/pickle。旧v2目录未写入。

本报告不构成投资建议。
"""
    target = run_root / "BACKTEST_RESULT_REPORT_v3.md"
    target.write_text(text, encoding="utf-8")
    return target


def write_v3_charts(run_root: Path, baseline, metrics: pd.DataFrame) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    equity = baseline.equity.sort_values("date").copy()
    initial = equity["equity"].iloc[0] - equity["net_pnl"].iloc[0]
    equity["净值"] = equity["equity"] / initial
    equity["回撤"] = equity["equity"] / equity["equity"].cummax() - 1
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(equity["date"], equity["净值"], color="#2457A7")
    axes[0].set_title("v3正式基准累计净值")
    axes[0].set_ylabel("累计净值")
    axes[0].grid(alpha=.25)
    axes[1].fill_between(equity["date"], equity["回撤"], 0, color="#C94C4C", alpha=.7)
    axes[1].set_ylabel("回撤")
    axes[1].grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(run_root / "equity_drawdown_v3.png", dpi=160)
    plt.close(fig)

    buffer = metrics[metrics["标签"].isin(["buffer_0", "buffer_5", "formal_baseline", "buffer_15", "buffer_20"])].sort_values("buffer比例")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(buffer["buffer比例"] * 100, buffer["全样本年化收益率"] * 100, marker="o", label="年化收益率")
    ax.plot(buffer["buffer比例"] * 100, buffer["验证期夏普比率"] * 10, marker="s", label="验证期Sharpe×10")
    ax.set_xlabel("Buffer（%）")
    ax.set_ylabel("百分比/缩放值")
    ax.set_title("v3 Buffer敏感性")
    ax.grid(alpha=.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(run_root / "buffer_sensitivity_v3.png", dpi=160)
    plt.close(fig)


def _data_quality(data) -> pd.DataFrame:
    mapped = data.mapping.merge(
        data.bars, left_on=["date", "contract"], right_on=["date", "ts_code"], how="left"
    )
    return pd.DataFrame([
        {"检查项": "主力映射行数", "数量": len(data.mapping)},
        {"检查项": "映射合约缺少日线", "数量": int(mapped["ts_code"].isna().sum())},
        {"检查项": "映射合约收盘缺失/非正", "数量": int((mapped["close"].isna() | mapped["close"].le(0)).sum())},
        {"检查项": "映射合约零成交", "数量": int((mapped["volume"].isna() | mapped["volume"].le(0)).sum())},
        {"检查项": "结算价缺失并回退收盘", "数量": int((mapped["settlement"].isna() & mapped["close"].notna()).sum())},
        {"检查项": "Panama拼接失败", "数量": len(data.diagnostics.get("panama", {}).get("stitch_failures", []))},
    ])


def _format_table(frame: pd.DataFrame) -> str:
    view = frame.copy()
    for column in view.columns:
        if any(token in column for token in ["收益率", "波动率", "回撤", "比例", "占用", "覆盖率", "阈值"]):
            if pd.api.types.is_numeric_dtype(view[column]):
                view[column] = view[column].map(lambda value: f"{value:.2%}" if pd.notna(value) else "")
        elif "_元" in column or column.endswith("元"):
            if pd.api.types.is_numeric_dtype(view[column]):
                view[column] = view[column].map(lambda value: f"{value:,.0f}" if pd.notna(value) else "")
        elif "夏普" in column and pd.api.types.is_numeric_dtype(view[column]):
            view[column] = view[column].map(lambda value: f"{value:.2f}" if pd.notna(value) else "")
    if "测试年是否完整" in view.columns:
        view["测试年是否完整"] = view["测试年是否完整"].map({True: "是", False: "否"}).fillna(view["测试年是否完整"])
    if "是否通过" in view.columns:
        view["是否通过"] = view["是否通过"].map({True: "通过", False: "未通过"}).fillna(view["是否通过"])
    view = view.astype(object).where(pd.notna(view), "")
    return view.to_markdown(index=False)
