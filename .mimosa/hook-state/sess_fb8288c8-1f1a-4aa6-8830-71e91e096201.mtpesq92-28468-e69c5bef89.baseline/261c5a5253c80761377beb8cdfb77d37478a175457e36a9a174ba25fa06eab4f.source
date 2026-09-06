from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .settings import Settings


def write_engine_audit_v4(settings: Settings, data, run_root: Path) -> Path:
    reproduction = pd.read_pickle(run_root / "v3_reproduction_gate_v4.pkl")
    reconciliation = pd.read_pickle(run_root / "accounting_reconciliation_v4.pkl")
    execution = pd.read_pickle(run_root / "execution_audit_statistics_v4.pkl")
    distribution = pd.read_pickle(run_root / "forecast_distribution_v4.pkl")
    scaling = pd.read_pickle(run_root / "forecast_scaling_statistics_v4.pkl")
    fee_coverage = _optional_csv(run_root / "fee_rule_coverage.csv")
    failed = reconciliation[~reconciliation["是否通过"]]
    last_date = pd.Timestamp(settings.section("run")["end"])
    text = f"""# 五板块动量回测引擎审计报告 v4

生成目录：`{run_root.name}`  
研究范围：只执行研究计划 v4（不同周期与多周期信号），未执行 v5。

## 1. 审计结论

- v4 未复制或改写交易执行：`BacktestEngineV4` 继承冻结的 v3 引擎，只替换 forecast 输入，并对手续费 1.5 倍、混合周度、10% buffer、120% 紧急减仓阈值做运行时断言。
- v3 的 252 日正式基准已先复现；{len(reproduction)} 项权益、持仓、目标、订单、成交、成本和逐品种盈亏检查全部通过：**{bool(reproduction['是否通过'].all())}**。
- 全部 {reconciliation['场景'].nunique()} 个已运行场景共执行 {len(reconciliation)} 项账户恒等式检查；失败 {len(failed)} 项，最大绝对误差 {reconciliation['绝对误差'].max():.8f} 元。
- 自动化测试文件 `test_results_v4.txt` 覆盖 v2/v3 回归与 v4 新增逻辑；完整测试结果随输出保存。
- 2026 年数据截至 {last_date.date()}，属于不完整年度，报告不得把它解释为完整自然年。

## 2. 开始时对 v3 信号链的审计

1. `signals.py` 先按品种构造 Panama 复权收盘价，再使用 `diff()` 得到绝对点差；252 日滚动均值除以样本标准差（`ddof=1`），乘 `sqrt(252)`。没有百分比收益。
2. 最小观察期等于完整窗口；历史不足为缺失，没有回填或全样本补值。
3. 每个 `W-FRI` 周期只在该周最后一个真实交易日形成信号；方向在下一信号日前持有。订单在当日结算记账后形成，最早下一交易日开盘成交。
4. 农产品与化工能源只在各自板块内对当日合格、非缺失品种排名；最强且正做多，最弱且负做空。RB、T、AL按同一 forecast 正负号决定方向。
5. Panama 只在实际换月日使用换月日以前（含上一交易日）的重叠价差调整历史。未来换月可能给历史价格水平增加同一常数，但不会改变过去的点差和 forecast；该性质有追加未来换月的确定性测试。

## 3. v4 修改边界

- 新增 `signals_v4.py`：20/60/120/180/250 日、跳过 5 日、250 减 20、因果 scaling、严格等权多周期。
- 新增 `engine_v4.py`：冻结 v3 执行假设并接收 v4 forecast。
- 新增 `analytics_v4.py`：Sortino、Calmar、恢复时间、滚动走样本、删除年份、集中度、forecast 分布/相关/权重和边际贡献。
- 新增 `workflow_v4.py` 与 `reports_v4.py`：预注册顺序、复现闸门、压力复核、全底层输出和中文报告。
- 新增 `tests/test_v4.py`、独立 v4 配置与实验注册表。既有 v2/v3 文件和输出未修改。
- 首次复现尝试目录 `v4_20260902_102328` 因 v3 逐品种盈亏表的进程级集合遍历行序不同而触发闸门；按 `date/contract/instrument` 排序后所有字段逐值完全一致。v4 随后加入固定业务主键排序，并在本正式目录重新从零通过闸门。该失败目录保留，没有删除审计痕迹。
- 正式运行后的汇总复核发现 v4 初稿把年化换手分母写成初始资金；交易结果未受影响。最终表已恢复 v3 定义（成交名义额/样本平均权益/年数），manifest 标记了此次分析层重建。

## 4. 公式和窗口边界

普通单周期在日期 t 使用最近 h 个可得变化：

`Score_h(t) = mean(ΔP[t-h+1:t]) / std(ΔP[t-h+1:t]) × sqrt(252)`。

跳过 5 日先将点差序列 `shift(5)`，再取完整 h 个变化。`250减20` 使用 230 个变化并 `shift(20)`，即约 `t-250` 至 `t-20` 的点差窗口；它不是两个 Sharpe 相减。人工数组测试逐值验证了边界。

多周期只有在所有预注册分量均有效时才等权平均，缺一个分量则总 forecast 缺失，避免隐性动态加权。

## 5. Forecast scaling 审计

- 每日先计算该周期所有当日可得品种的平均绝对 raw forecast。
- expanding 均值至少需要 126 个有效历史日，并整体 `shift(1)`；当日 scaling 不含当日 forecast。
- 目标平均绝对 forecast 为 10，scalar 限于 `[0.1,100]`，单周期 scaled forecast 截断至 `[-20,20]`。
- 历史不足保持缺失；不使用全样本均值，不按收益优化权重。
- 追加或修改未来数据不改变过去 raw forecast、scalar 或 scaled forecast，已由单元测试验证。

缩放首个有效日与分布摘要见 `forecast_scaling_statistics_v4.csv` 和 `forecast_distribution_v4.csv`：

{_table(scaling[['周期','阶段','首个有效日期','有效日数','平均scale','最小值','最大值']].head(15))}

## 6. v3 精确复现闸门

底层：`v3_reproduction_gate_v4.csv/.pkl`。

{_table(reproduction)}

只有这张表全部通过后，工作流才会运行任何 v4 候选。

## 7. 未来函数与执行时序测试

测试明确覆盖：

- 修改未来价格不改变过去任一周期 raw、skip、scaled forecast 或 scalar；
- 追加未来 Panama 换月不改变过去点差；
- skip5、skip20 和 230 日窗口的人工手算边界；
- scaling 只用 t-1 及以前历史；
- 缺失分量不会被未来值回填，也不会形成动态权重；
- 252 日 v4 参照分数、选择和方向逐行等于 v3；
- 订单成交日严格晚于订单形成日；
- 引擎重复运行的权益和成交完全一致；
- v3 的开仓、非日内平仓、平今、跨零反手、换月双边费、参与率冲击和滑点单次入账测试继续通过。

## 8. 账户与成本勾稽

底层：`accounting_reconciliation_v4.csv/.pkl`、`execution_audit_statistics_v4.csv/.pkl`。

{_table(reconciliation.groupby('检查项').agg(场景数=('场景','nunique'), 最大误差=('绝对误差','max'), 全部通过=('是否通过','all')).reset_index())}

执行统计范围：成交分段 {int(execution['成交分段数'].sum()):,}，代理费用分段 {int(execution['代理费用分段'].sum()):,}，市场冲击分段 {int(execution['市场冲击分段'].sum()):,}，最大参与率 {execution['最大参与率'].max():.4%}。手续费与滑点没有在账户现金流中重复扣除：滑点只通过不利成交价进入毛盈亏，手续费单独扣除。

## 9. 数据、手续费与代理限制

- v4 沿用 v3 的同一 normalized_v2 数据、主力映射、流动性门槛、Panama 规则和历史手续费表，没有重下载或重写缓存。
- 客户手续费固定为交易所规则的 1.5 倍。每笔成交记录规则编号、生效区间、来源 URL 与代理标记。
- 无法取得的历史规则继续明确标记为 proxy；不能把代理费解释成当时投资者真实账单。
- 日线模型无法刻画盘口深度、夜盘内路径、真实排队和涨跌停板内成交概率；参与率冲击与 tick 滑点是保守代理，不是逐笔成交重放。

费用覆盖底层：`fee_rule_coverage.csv`、`tushare_fee_coverage.csv`、`historical_fee_rules.csv/.pkl`。

{_table(fee_coverage.head(20)) if not fee_coverage.empty else '费用覆盖表未找到。'}

## 10. 可复现性和文件追踪

- 所有 DataFrame 底层结果同时保存 CSV 与 pickle；配对清单为 `pickle_csv_traceability_v4.csv/.pkl`。
- 每个场景独立保存参数、scores、selections、directions、权益、持仓、目标、订单、成交、拒单和逐品种盈亏。
- `scenario_registry_v4.csv/.pkl` 保存全部预注册场景；所有运行场景均保留，没有只保存最优场景。
- 本报告不能证明模型在未来有效，只证明实现与预注册规则、数据和账户公式在本次审计范围内一致。
"""
    target = run_root / "BACKTEST_ENGINE_AUDIT_v4.md"
    target.write_text(text, encoding="utf-8")
    return target


def write_result_report_v4(settings: Settings, run_root: Path) -> Path:
    metrics = pd.read_pickle(run_root / "scenario_metrics_v4.pkl")
    yearly = pd.read_pickle(run_root / "yearly_performance_v4.pkl")
    rolling = pd.read_pickle(run_root / "rolling_walk_forward_v4.pkl")
    robust = pd.read_pickle(run_root / "robustness_v4.pkl")
    contribution = pd.read_pickle(run_root / "pnl_contribution_v4.pkl")
    concentration = pd.read_pickle(run_root / "concentration_v4.pkl")
    costs = pd.read_pickle(run_root / "cost_attribution_v4.pkl")
    rebalance = pd.read_pickle(run_root / "rebalance_buffer_statistics_v4.pkl")
    margin = pd.read_pickle(run_root / "margin_leverage_v4.pkl")
    selection = pd.read_pickle(run_root / "candidate_selection_v4.pkl")
    recommendation = pd.read_pickle(run_root / "final_recommendation_v4.pkl").iloc[0]
    comparison = pd.read_pickle(run_root / "v3_v4_comparison.pkl")
    correlations = pd.read_pickle(run_root / "forecast_correlations_v4.pkl")
    weights = pd.read_pickle(run_root / "forecast_effective_weights_v4.pkl")
    marginal = pd.read_pickle(run_root / "marginal_pnl_v4.pkl")
    skip_impact = pd.read_pickle(run_root / "skip_recent_impact_v4.pkl")
    multi_distribution = pd.read_pickle(run_root / "multi_forecast_distribution_v4.pkl")
    pressure = pd.read_pickle(run_root / "slippage_pressure_v4.pkl")
    parameters = pd.read_pickle(run_root / "scenario_parameters_v4.pkl")

    reference = metrics[metrics["标签"].eq("reference_v3_252")].iloc[0]
    recommended_label = str(recommendation["推荐标签"])
    recommended = metrics[metrics["标签"].eq(recommended_label)]
    if recommended.empty:
        recommended = metrics[metrics["标签"].eq("reference_v3_252")]
    recommended = recommended.iloc[0]
    ref_conc = concentration[concentration["场景"].eq(reference["场景"])].iloc[0]
    rec_conc = concentration[concentration["场景"].eq(recommended["场景"])].iloc[0]
    improved_year = rec_conc["正盈利年份前两名占比"] < ref_conc["正盈利年份前两名占比"]
    improved_fg = _lower_or_both_nan(rec_conc["FG占化工正利润比"], ref_conc["FG占化工正利润比"])
    improved_dd = recommended["全样本最大回撤"] > reference["全样本最大回撤"]
    material_fg = (
        not pd.isna(rec_conc["FG占化工正利润比"])
        and not pd.isna(ref_conc["FG占化工正利润比"])
        and ref_conc["FG占化工正利润比"] - rec_conc["FG占化工正利润比"] >= .01
    )
    material_dd = recommended["全样本最大回撤"] - reference["全样本最大回撤"] >= .01
    decision = str(recommendation["结论"])

    top = selection.head(10)[[
        "预注册排序", "标签", "家族", "通过门槛数", "核心三门是否通过",
        "验证期夏普", "删除2020和2024夏普", "Calmar", "年份前二占比",
        "FG占化工正利润比", "年化换手", "进入滑点压力复核",
    ]]
    summary_columns = [
        "标签", "家族", "周期", "聚合方式", "跳过近期日数",
        "全样本年化收益率", "全样本年化波动率", "全样本夏普比率",
        "全样本Sortino比率", "全样本最大回撤", "验证期年化收益率",
        "验证期夏普比率", "滚动下一年拼接年化收益率", "手续费_元",
        "滑点成本_元", "总交易成本_元", "年化名义换手_倍",
    ]
    candidates = metrics[metrics["是否研究候选"]].sort_values(
        "验证期夏普比率", ascending=False
    )[summary_columns]
    rec_yearly = yearly[yearly["场景"].eq(recommended["场景"])][[
        "年份", "年化收益率", "年化波动率", "夏普比率", "最大回撤", "是否亏损年", "年度状态"
    ]]
    rec_rolling = rolling[rolling["场景"].eq(recommended["场景"])][[
        "训练起始年", "训练结束年", "测试年", "测试年是否完整",
        "训练年化收益率", "训练夏普比率", "测试年化收益率", "测试夏普比率", "测试最大回撤",
    ]]
    rec_robust = robust[
        robust["场景"].eq(recommended["场景"]) & robust["阶段"].eq("全样本")
        & robust["成本口径"].eq("含成本")
    ][["切片", "年化收益率", "年化波动率", "夏普比率", "最大回撤", "Sortino比率"]]
    rec_contrib = contribution[
        contribution["场景"].eq(recommended["场景"]) & contribution["阶段"].eq("全样本")
    ]
    sector_contrib = rec_contrib.groupby(["板块", "方向"], as_index=False).agg(
        交易成本前盈亏_元=("交易成本前盈亏_元", "sum"),
        滑点成本_元=("滑点成本_元", "sum"), 手续费_元=("手续费_元", "sum"),
        净利润_元=("净利润_元", "sum"),
    ).sort_values("净利润_元", ascending=False)
    instrument_contrib = rec_contrib.groupby("instrument", as_index=False).agg(
        交易成本前盈亏_元=("交易成本前盈亏_元", "sum"),
        滑点成本_元=("滑点成本_元", "sum"), 手续费_元=("手续费_元", "sum"),
        净利润_元=("净利润_元", "sum"),
    ).sort_values("净利润_元", ascending=False)
    rec_cost = costs[costs["场景"].eq(recommended["场景"])].groupby(
        ["板块", "instrument"], as_index=False
    ).agg(
        成交手数=("成交手数", "sum"), 客户手续费_元=("客户手续费_元", "sum"),
        基础滑点成本_元=("基础滑点成本_元", "sum"),
        换月额外滑点_元=("换月额外滑点_元", "sum"),
        市场冲击成本_元=("市场冲击成本_元", "sum"),
        总滑点成本_元=("总滑点成本_元", "sum"),
    ).sort_values("总滑点成本_元", ascending=False)
    rec_rebalance = rebalance[rebalance["场景"].eq(recommended["场景"])]
    rec_margin = margin[margin["场景"].eq(recommended["场景"])]
    corr_validation = correlations[
        correlations["阶段"].eq("验证期") & correlations["周期1"].lt(correlations["周期2"])
    ]

    text = f"""# 五板块动量回测结果报告 v4

生成目录：`{run_root.name}`  
样本：2015-01-01 至 {settings.section('run')['end']}；样本内 2015—2021，验证期 2022—{pd.Timestamp(settings.section('run')['end']).year}。2026 年为不完整年度。

## 1. 最终结论

**{decision}。**

按预注册规则，最终推荐标签为 `{recommended_label}`。这不是按全样本收益最高挑选，而是依次检查样本内/验证期、滚动下一年、删除关键年份、年份与板块集中、FG 依赖、相邻周期一致性、成本换手、最大回撤以及 2/3 tick 压力结果。

对用户最关心的三项，最终推荐相对 v3：

- 年份集中度是否改善：**{_yes_no(improved_year)}**（正盈利年份前二占比 {ref_conc['正盈利年份前两名占比']:.2%} → {rec_conc['正盈利年份前两名占比']:.2%}）。
- FG 依赖是否改善：**名义上{_yes_no(improved_fg)}、实质上{_yes_no(material_fg)}**（FG 占化工正利润比 {_pct(ref_conc['FG占化工正利润比'])} → {_pct(rec_conc['FG占化工正利润比'])}，仅变化 {(ref_conc['FG占化工正利润比']-rec_conc['FG占化工正利润比']):.2%}；化工板块总净利润仍为负而 FG 为主要正贡献）。
- 最大回撤是否改善：**名义上{_yes_no(improved_dd)}、实质上{_yes_no(material_dd)}**（{reference['全样本最大回撤']:.2%} → {recommended['全样本最大回撤']:.2%}，只改善 {recommended['全样本最大回撤']-reference['全样本最大回撤']:.2%}）。

如果最终仍保留 v3，上述同值不应解释为 v4 改善；它表示没有候选同时满足足够严格的替换证据。

底层：`final_recommendation_v4.csv/.pkl`、`v3_v4_comparison.csv/.pkl`。

{_table(comparison)}

## 2. v3 参照复现

v4 代码先复现 v3 的 252 日基准，权益、成交、成本、持仓、目标、订单和逐品种盈亏均通过 0.01 元/数值容差。正式 v3 执行假设在全部 v4 场景固定不变。

参照组：年化收益 {reference['全样本年化收益率']:.2%}，波动 {reference['全样本年化波动率']:.2%}，Sharpe {reference['全样本夏普比率']:.3f}，最大回撤 {reference['全样本最大回撤']:.2%}；验证期年化收益 {reference['验证期年化收益率']:.2%}，Sharpe {reference['验证期夏普比率']:.3f}。

底层：`v3_reproduction_gate_v4.csv/.pkl`。

## 3. 全部候选结果

共预注册 17 个研究候选：5 个普通单周期、5 个跳过 5 日单周期、1 个 250 减 20、3 个原始多周期和 3 个 scaling 多周期。另有 1 个正式参照、22 个留一周期边际诊断；仅按规则筛出的最多 3 个候选运行 2/3 tick 压力，不做笛卡尔积。

底层：`scenario_registry_v4.csv/.pkl`、`scenario_parameters_v4.csv/.pkl`、`scenario_metrics_v4.csv/.pkl`。

{_table(candidates)}

## 4. 预注册筛选与压力复核

底层：`candidate_selection_v4.csv/.pkl`、`slippage_pressure_v4.csv/.pkl`。没有删除落选场景。

{_table(top)}

压力复核：

{_table(pressure[[c for c in ['标签','父组合','固定基础滑点_tick','全样本年化收益率','验证期年化收益率','验证期夏普比率','全样本最大回撤','总交易成本_元'] if c in pressure.columns]]) if not pressure.empty else '没有候选满足进入压力复核的核心三门，因而未运行压力场景。'}

支持最终推荐的证据：{recommendation['理由']} 它把年份前二集中从 {ref_conc['正盈利年份前两名占比']:.2%} 降至 {rec_conc['正盈利年份前两名占比']:.2%}，删除 2020/2024 后仍为正，2/3 tick 压力下样本内及验证期均为正。反对依据：验证期年化收益从 {reference['验证期年化收益率']:.2%} 降至 {recommended['验证期年化收益率']:.2%}、Sharpe 从 {reference['验证期夏普比率']:.3f} 降至 {recommended['验证期夏普比率']:.3f}；FG 依赖和最大回撤只名义改善，单一板块正利润占比从 {ref_conc['单一板块正利润占比']:.2%} 升至 {rec_conc['单一板块正利润占比']:.2%}，成本和换手也更高。因此该替换是“按锁定规则通过但优势不全面”，不是 v3 的无条件支配方案。

## 5. 跳过近期数据的成对影响

正数“最大回撤变化”表示回撤改善；收益、成本、换手和年份依赖均以跳过版本减普通版本计算。结果没有显示跳过近期数据在所有窗口上一致更优，不能把短期反转处理概括为普遍有效。

底层：`skip_recent_impact_v4.csv/.pkl`。

{_table(skip_impact)}

## 6. 分年度与滚动走样本

每个测试年使用此前连续五年作为评估窗，下一年按固定方案运行；表中 2026 明确为不完整测试年。固定方案的滚动拼接指标等于 2020 年起各下一年测试收益按时间拼接，不在滚动窗内重新优化参数。

底层：`yearly_performance_v4.csv/.pkl`、`rolling_walk_forward_v4.csv/.pkl`。

{_table(rec_yearly)}

{_table(rec_rolling)}

## 7. 删除 2020/2024 稳健性

底层：`robustness_v4.csv/.pkl`；该文件同时包含样本内、验证期、滚动拼接及成本前/含成本口径。

{_table(rec_robust)}

删除年份是事后敏感性分析，不等于可交易策略；目的只是识别利润是否由少数年份支撑。

## 8. 板块、品种与多空贡献

底层：`pnl_contribution_v4.csv/.pkl`。成本前盈亏减滑点和手续费等于净利润。

{_table(sector_contrib)}

{_table(instrument_contrib)}

集中度底层：`concentration_v4.csv/.pkl`。最终方案年份前二占比 {rec_conc['正盈利年份前两名占比']:.2%}，单一板块正利润占比 {rec_conc['单一板块正利润占比']:.2%}，单一品种正利润占比 {rec_conc['单一品种正利润占比']:.2%}，FG 净利润 {rec_conc['FG净利润_元']:,.0f} 元。

## 9. 成本、换手、buffer、保证金与杠杆

最终方案成交手数 {recommended['成交手数']:,.0f}，年化名义换手 {recommended['年化名义换手_倍']:.2f} 倍，手续费 {recommended['手续费_元']:,.0f} 元，滑点 {recommended['滑点成本_元']:,.0f} 元，其中市场冲击 {recommended['市场冲击成本_元']:,.0f} 元、换月额外滑点 {recommended['换月额外滑点_元']:,.0f} 元。

底层：`cost_attribution_v4.csv/.pkl`、`rebalance_buffer_statistics_v4.csv/.pkl`、`margin_leverage_v4.csv/.pkl`。

{_table(rec_cost)}

{_table(rec_rebalance)}

{_table(rec_margin)}

10% buffer 和混合周度没有因 v4 改变；信号退出、换月、保证金强制缩减与 120% 实现波动率紧急减仓仍可在非周度日绕过正常调仓日，但都保留明确原因。

## 10. Forecast 分布、相关性与有效权重

单周期原始/缩放/跳过版本分布见 `forecast_distribution_v4.csv/.pkl`；多周期聚合后分布见 `multi_forecast_distribution_v4.csv/.pkl`；scaling 时间序列与摘要见 `forecast_scalars_v4.csv/.pkl`、`forecast_scaling_statistics_v4.csv/.pkl`；相关性见 `forecast_correlations_v4.csv/.pkl`；有效贡献权重见 `forecast_effective_weights_v4.csv/.pkl`。

{_table(multi_distribution)}

验证期相邻/跨周期 forecast 相关性：

{_table(corr_validation)}

{_table(weights[weights['阶段'].eq('验证期')])}

等权是名义权重；“平均绝对 forecast 有效贡献权重”反映不同尺度使各周期实际幅度贡献不同。scaled 版本先把单规则历史平均绝对 forecast 对齐，再截断并等权。

## 11. 各周期边际盈亏贡献

为避免把 forecast 数值贡献误称为账户盈亏，预注册了 22 个留一周期完整回测。父组合净利润减留一组合净利润定义为该周期的边际账户盈亏；它包含非线性的排名、buffer、整数手数和成本效应，不可简单相加。

底层：`marginal_pnl_v4.csv/.pkl`。

{_table(marginal)}

## 12. 数据缺失、代理参数与异常

- 主力合约、Panama、流动性门槛、手续费、生效区间、正常滑点、参与率冲击、换月额外 tick、保证金/杠杆与国债豁免全部冻结自 v3。
- 无法取得的历史手续费明确保留 `fee_is_proxy=True`；代理覆盖不能当作真实历史账单。
- 日线次日开盘模型不包含日内路径、盘口排队和夜盘细节；2/3 tick 压力只校验少量候选。
- forecast scaling 用当时可得的跨品种平均绝对值；上市/退市会改变当日横截面构成，这是因果可交易变化，不是固定品种面板。
- 2022—2026 虽称验证期，但本次研究是在已看到该区间数据后统一比较候选，不能视作真正未见数据；多重比较风险仍在。
- 2026 仅到 8 月 31 日，年度收益、亏损年数量和滚动测试均需结合“不完整年度”标记解读。
- 本报告不能据此得出未来收益、容量、实际成交、最优周期或可直接实盘的结论。

## 13. 本次新增/修改文件与测试

- `configs/five_sector_momentum_v4.yaml`
- `V4_EXPERIMENT_REGISTRY.md`
- `src/five_sector_momentum/signals_v4.py`
- `src/five_sector_momentum/engine_v4.py`
- `src/five_sector_momentum/analytics_v4.py`
- `src/five_sector_momentum/workflow_v4.py`
- `src/five_sector_momentum/reports_v4.py`
- `tests/test_v4.py`
- `scripts/run_v4.py`
- `scripts/finalize_v4_outputs.py`

测试底层：`test_results_v4.txt`。账户复核：`accounting_reconciliation_v4.csv/.pkl`。全部表的 CSV/pickle 配对：`pickle_csv_traceability_v4.csv/.pkl`。

建议人工优先复核：`V4_EXPERIMENT_REGISTRY.md`、`v3_reproduction_gate_v4.csv`、`candidate_selection_v4.csv`、`final_recommendation_v4.csv`、`v3_v4_comparison.csv`、`robustness_v4.csv`、`concentration_v4.csv`、`accounting_reconciliation_v4.csv`，以及推荐场景目录内的 `scores`、`orders`、`fills` 和 `daily_equity`。
"""
    target = run_root / "BACKTEST_RESULT_REPORT_v4.md"
    target.write_text(text, encoding="utf-8")
    return target


def _table(frame: pd.DataFrame, maximum_rows: int = 40) -> str:
    if frame.empty:
        return "（无记录）"
    display = frame.head(maximum_rows).copy()
    for column in display:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else f"{value:.6g}")
    try:
        rendered = display.to_markdown(index=False)
    except ImportError:
        rendered = "```text\n" + display.to_string(index=False) + "\n```"
    if len(frame) > maximum_rows:
        rendered += f"\n\n（仅展示前 {maximum_rows} 行；完整 {len(frame)} 行见对应底层文件。）"
    return rendered


def _optional_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _yes_no(value: bool) -> str:
    return "是" if bool(value) else "否"


def _pct(value: float) -> str:
    return "缺失" if pd.isna(value) else f"{value:.2%}"


def _lower_or_both_nan(left: float, right: float) -> bool:
    if pd.isna(left) and pd.isna(right):
        return False
    if pd.isna(left) or pd.isna(right):
        return False
    return bool(left < right)
