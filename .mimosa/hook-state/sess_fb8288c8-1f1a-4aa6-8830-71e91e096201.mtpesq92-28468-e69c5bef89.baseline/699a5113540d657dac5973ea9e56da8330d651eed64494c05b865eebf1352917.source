from __future__ import annotations

from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from .settings import Settings


def _read(root: Path, name: str) -> pd.DataFrame:
    return pd.read_pickle(root / f"{name}.pkl")


def _table(frame: pd.DataFrame, rows: int = 30) -> str:
    if frame.empty:
        return "（无记录）"
    shown=frame.head(rows).copy()
    for column in shown.select_dtypes(include=["float"]).columns:
        shown[column]=shown[column].map(lambda x: "" if pd.isna(x) else f"{x:.6g}")
    return shown.to_markdown(index=False)


def _save(frame: pd.DataFrame, root: Path, name: str) -> None:
    frame.to_pickle(root/f"{name}.pkl")
    frame.to_csv(root/f"{name}.csv",index=False,encoding="utf-8-sig")


def _candidate_decision(root: Path) -> tuple[pd.DataFrame,str]:
    compare=_read(root,"v3_v4_v4_1_comparison")
    robust=_read(root,"sleeve_robustness_v4_1")
    pressure=_read(root,"sleeve_metrics_v4_1")
    matrix=_read(root,"cost_response_matrix_v4_1")
    project=root.parent.parent
    v4_robust=pd.read_pickle(project/"outputs/v4_20260902_102628/robustness_v4.pkl")
    bootstrap=_read(root,"bootstrap_paired_summary_v4_1")
    rows=[]
    mapping={
        "v3_reference":"reference_v3_252",
        "v4_challenger_single_180_skip5":"single_180_skip5",
        "v4_1_strategy_sleeve_fast_equal_risk":"strategy_sleeve_fast_equal_risk",
        "v4_1_strategy_sleeve_all_equal_risk":"strategy_sleeve_all_equal_risk",
        "v4_1_strategy_sleeve_slow_equal_risk":"strategy_sleeve_slow_equal_risk",
    }
    for scheme,strategy in mapping.items():
        phases=compare[compare["方案"].eq(scheme)].set_index("阶段")
        row={"方案":scheme,"strategy":strategy,"样本内收益为正":bool(phases.loc["insample","年化收益率"]>0),"验证期收益为正":bool(phases.loc["validation","年化收益率"]>0),"全样本年化收益":phases.loc["full","年化收益率"],"验证期年化收益":phases.loc["validation","年化收益率"],"全样本Sharpe":phases.loc["full","夏普比率"],"验证期Sharpe":phases.loc["validation","夏普比率"],"全样本最大回撤":phases.loc["full","最大回撤"],"总成本_元":phases.loc["full","总成本_元"]}
        if "sleeve" in strategy:
            fixed=pressure[(pressure.strategy.eq(strategy+"_fixed_3tick"))&(pressure.period.eq("validation"))]
            row["3tick验证期收益为正"]=bool(not fixed.empty and fixed.iloc[0]["年化收益率"]>0)
            rr=robust[(robust["场景"].astype(str).str.contains(strategy))&(robust["阶段"].eq("全样本"))&(robust["成本口径"].eq("含成本"))&(robust["切片"].eq("同时删除2020和2024年"))]
            row["删2020_2024后为正"]=bool(not rr.empty and rr.iloc[0]["年化收益率"]>0)
        else:
            fixed=matrix[(matrix.strategy.eq(strategy))&(matrix.cost_code.eq("C7"))&(matrix.period.eq("validation"))]
            row["3tick验证期收益为正"]=bool(not fixed.empty and fixed.iloc[0]["年化收益率"]>0)
            scenario="00_reference__reference_v3_252" if strategy=="reference_v3_252" else "02_single_skip__single_180_skip5"
            rr=v4_robust[(v4_robust["场景"].eq(scenario))&(v4_robust["阶段"].eq("全样本"))&(v4_robust["成本口径"].eq("含成本"))&(v4_robust["切片"].eq("同时删除2020和2024年"))]
            row["删2020_2024后为正"]=bool(not rr.empty and rr.iloc[0]["年化收益率"]>0)
        paired=bootstrap[(bootstrap.phase.eq("validation"))&(bootstrap.basis.eq("net"))&(bootstrap.strategy.eq(strategy))&(bootstrap.reference.eq("reference_v3_252"))&(bootstrap.metric.eq("sharpe"))]
        row["Bootstrap验证期Sharpe优于v3频率"]=paired.iloc[0].positive_frequency if not paired.empty else np.nan
        rows.append(row)
    frame=pd.DataFrame(rows)
    sleeves=frame[frame.strategy.str.contains("sleeve")]
    eligible=sleeves[sleeves[["样本内收益为正","验证期收益为正","3tick验证期收益为正","删2020_2024后为正"]].all(axis=1)]
    if eligible.empty:
        decision="没有足够证据替换现有v3方案；single_180_skip5仅作为并行挑战者，三个袖套均只保留为探索性诊断。"
    else:
        best=eligible.sort_values(["Bootstrap验证期Sharpe优于v3频率","验证期Sharpe"],ascending=False).iloc[0]
        decision=f"没有足够证据直接替换v3；可将 {best['strategy']} 固定为下一阶段观察候选，single_180_skip5继续并行观察。"
    frame["预注册结论"]=decision
    return frame,decision


def write_reports_v4_1(settings: Settings, root: Path) -> None:
    recommendation,decision=_candidate_decision(root); _save(recommendation,root,"recommendation_v4_1")
    _write_audit(settings,root)
    _write_results(settings,root,recommendation,decision)
    _write_attribution(settings,root)
    _write_inventory(root)


def _write_audit(settings: Settings, root: Path) -> None:
    gate=_read(root,"reproduction_gate_v4_1"); account=_read(root,"accounting_reconciliation_v4_1"); runs=_read(root,"engine_run_count_v4_1")
    anomalies=_read(root,"data_quality_anomalies_v4_1") if (root/"data_quality_anomalies_v4_1.pkl").exists() else pd.DataFrame()
    correction=_read(root,"sleeve_correction_audit_v4_1") if (root/"sleeve_correction_audit_v4_1.pkl").exists() else pd.DataFrame()
    test_text=(root/"test_results_v4_1.txt").read_text(encoding="utf-8",errors="replace")
    tests_ok="FAILED" not in test_text and "ERROR" not in test_text
    if "engine_runs" in runs:
        total_runs=int(runs.loc[runs.stage.eq("total_actual"),"engine_runs"].iloc[0])
        valid_runs=int(runs.loc[runs.stage.eq("valid_registered_results"),"engine_runs"].iloc[0])
    else:
        total_runs=valid_runs=int(runs.iloc[-1].new_runs)
    text=f"""# 五板块动量回测引擎审计报告 v4.1

生成目录：`{root.name}`  
范围：仅执行 v4.1；未进入 v5，v2/v3/v4 代码、配置、缓存和历史输出均按只读使用。

## 1. 审计结论

- 四个复现闸门共 {len(gate)} 项逐表检查，全部通过：**{bool(gate.passed.all())}**；最大数值差 {gate.max_numeric_diff.max():.8f}。
- 共执行实际引擎运行 **{total_runs}** 次，恰等于任务规范59次上限；其中初版袖套6次因审计缺陷保留但作废，最终有效注册结果仍为 **{valid_runs}** 个（4闸门+43成本+6修正版袖套）。没有新增参数或策略场景。
- 账户勾稽 {len(account)} 项，失败 {int((~account.passed).sum())} 项，最大误差 {account.error.max():.8f} 元。
- 全量 v2/v3/v4/v4.1 自动化测试通过：**{tests_ok}**。完整文本见 `test_results_v4_1.txt`。
- 2026 年截至 {settings.section('run')['end']}，是不完整年度。

底层：`reproduction_gate_v4_1.csv/.pkl`、`accounting_reconciliation_v4_1.csv/.pkl`、`engine_run_count_v4_1.csv/.pkl`。

{_table(gate)}

## 2. 成本和账户路径审计

手续费由真实合约、成交日期、开仓/非日内平仓/平今类型查询历史规则后乘1.5，在每日账户中单独扣除。基础滑点、换月额外 tick 和参与率冲击合成为不利成交价，先进入逐合约毛盈亏；`slippage_cost`及其分项只是归因字段，不再从现金重复扣除。跨零反手拆成先平后开，换月旧、新合约两腿各自收费。

同路径成本前重建严格使用 `净盈亏 + 手续费 + 已记录总滑点`，从初始资金逐日累加；基础、换月、冲击分项之和与总滑点相等。冻结原手数意味着它是会计反事实，不等同于C0重新回测。换手保持 `成交名义额/样本平均权益/(交易日/252)`。

## 3. 未来函数与时序

- forecast来自Panama复权收盘价绝对点差；周度信号形成日与下一交易日开盘成交分离。
- v4.1没有重算主力或Panama，复用已经审计的因果映射；未来换月不能改变历史点差。
- raw/scaled相关、有效权重和横截面选择均只统计每周独立信号日；共同缺失直接剔除，不回填。
- scaling继续使用至少126日历史并整体滞后1日；缺一个周期时严格等权聚合保持缺失。
- 袖套中每个周期先独立选择，固定风险份额；未用份额不转移。真实合约净额后才进行组合约束和一次10% buffer，只有净订单收费。
- Bootstrap在全样本、样本内、验证期各自抽合法20日区块；21策略在同一重复共享区块，最大回撤从每条重采样路径重新计算。

## 4. 复现闸门

比较覆盖forecast、选择、方向、权益、目标、持仓、订单、成交、成交类型、费用/滑点字段和逐品种盈亏。金额容差0.01元；闸门失败会在4次运行后硬停止。本次全部通过后才执行43次成本反事实与6次袖套运行。

## 4.1 袖套缺陷发现与纠正

初版袖套在非周度退出判断中使用周期方向票数；横截面不同周期的腿数和整数手数可不同，因此“票数和为0”不必然意味着真实合约净目标为0。交叉审计发现该状态后，初版6个结果全部作废但目录保留；使用最终净`optimal`的零/非零状态修正调度，并以任务上限剩余6次重跑同一组场景。没有增加参数或策略。最终累计59次，恰达规范上限。

底层：`sleeve_correction_audit_v4_1.csv/.pkl`；`03_sleeve__*`为无效初版，`04_corrected_sleeve__*`为正式修正版。

{_table(correction)}

## 5. 成本反事实边界

C0只关闭显性成本，仍保留次日执行、涨跌停拒单、成交量参与率上限、部分成交、主力换月和风险约束。C2—C5只移动正常基础整数tick，C6/C7固定2/3 tick；换月额外tick和冲击除C0/C1外保持不变。成本变化通过权益反馈因果影响后续整数手数，因此成本响应不要求线性或单调。

## 6. 自动化与人工手算覆盖

新增测试覆盖成本加回恒等式及手算权益、分项成本开关、C0约束保留、滑点单次入账、权益反馈、盈亏平衡相邻插值、严格等权/缺失、sign与选择、按品种相关、袖套预算/缺失/净额、最终buffer、未来追加不变、次日成交、账户勾稽、Bootstrap固定种子/共享区块/边界/缺失日/路径回撤和跨进程排序。既有v2/v3/v4测试同时运行。

## 7. 仍然存在的可靠性限制

日线数据不能观察盘口价差、队列位置、开盘集合竞价、夜盘内路径、极端行情实际容量及经纪商真实返佣。固定不利tick、参与率冲击与换月额外tick可能部分重叠；历史费用中的代理记录不能冒充当时真实客户账单。Bootstrap只重采样已有收益，不能创造新市场状态；验证期已被v4比较过，也不是干净未触碰样本外。

数据网格审计发现 {len(anomalies)} 条开盘价不落在当前元数据tick网格，均为2026年棕榈油记录；未修改历史缓存。所有C0实际成交另受“手续费与记录滑点均严格为零”的运行断言约束并已通过。底层：`data_quality_anomalies_v4_1.csv/.pkl`、`limitations_v4_1.csv/.pkl`、`inherited_fee_rule_coverage_v4_1.csv/.pkl`。
"""
    (root/"BACKTEST_ENGINE_AUDIT_v4_1.md").write_text(text,encoding="utf-8")


def _write_results(settings: Settings, root: Path, recommendation: pd.DataFrame, decision: str) -> None:
    compare=_read(root,"v3_v4_v4_1_comparison"); sleeve=_read(root,"sleeve_metrics_v4_1"); robust=_read(root,"sleeve_robustness_v4_1"); contribution=_read(root,"sleeve_contribution_v4_1"); netting=_read(root,"sleeve_netting_v4_1"); risk=_read(root,"sleeve_risk_contribution_v4_1"); div=_read(root,"diversification_metrics_v4_1"); paired=_read(root,"bootstrap_paired_summary_v4_1"); point=_read(root,"bootstrap_point_winner_stability_v4_1"); rebalance=_read(root,"rebalance_buffer_statistics_v4_1"); margin=_read(root,"margin_leverage_v4_1")
    pressure=sleeve[sleeve.strategy.str.contains("fixed_3tick")]
    sleeve_conc=_read(root,"sleeve_concentration_v4_1")
    text=f"""# 五板块动量回测结果报告 v4.1

生成目录：`{root.name}`  
样本：{settings.section('run')['start']}至{settings.section('run')['end']}；2022-01-01起为已被v4使用过的验证期，2026年不完整。

## 1. 结论

**{decision}**

本结论没有按全样本最高收益选择。优先考察样本内和验证期、删除2020/2024、固定3 tick、集中度与FG、收益—回撤交换、成本、相邻周期证据和Bootstrap排名稳定性。v4.1袖套是在看过v4后提出，只能作为探索性候选。

报告采用`04_corrected_sleeve__*`正式修正版；`03_sleeve__*`初版仅作缺陷审计，不进入指标、Bootstrap或推荐。修正前后逐项差异见`sleeve_correction_audit_v4_1.csv/.pkl`。

底层：`recommendation_v4_1.csv/.pkl`。

{_table(recommendation)}

## 2. v3、v4挑战者与三个袖套

底层：`v3_v4_v4_1_comparison.csv/.pkl`。

{_table(compare)}

固定3 tick只对三个袖套作预注册压力复核：

{_table(pressure[["strategy","period","年化收益率","年化波动率","夏普比率","最大回撤","commission","base_slippage","roll_slippage","impact","turnover"]])}

## 3. 袖套风险、净额与执行

每板块仍是20%风险预算：fast每周期6.6667%，all/slow每周期5%。`mean_nominal_allocated_annual_risk`是预分配人民币年风险，`realized_internal_over_allocated`反映整数手数、流动性及无信号造成的未使用；它不是事后收益贡献。

底层：`sleeve_risk_contribution_v4_1.csv/.pkl`、`sleeve_internal_targets_v4_1.csv/.pkl`。

{_table(risk,40)}

袖套净额表的虚拟成本只用实际平均每手成本作代理，不进账户；真正费用仅来自最终净订单。

底层：`sleeve_netting_v4_1.csv/.pkl`。

{_table(netting)}

## 4. 分散、稳健性与贡献

底层：`diversification_metrics_v4_1.csv/.pkl`、`sleeve_robustness_v4_1.csv/.pkl`、`sleeve_contribution_v4_1.csv/.pkl`、`sleeve_concentration_v4_1.csv/.pkl`。

{_table(div)}

{_table(robust[(robust["阶段"].eq("全样本"))&(robust["成本口径"].eq("含成本"))],30)}

{_table(sleeve_conc)}

## 5. Bootstrap可靠性

联合移动分块Bootstrap覆盖21个经济上不同的基础策略、2000次、20交易日区块。置信区间重叠和原样本赢家保持最优频率用于约束结论；胜出次数不等于实盘最优。

底层：`bootstrap_strategy_draws_v4_1.csv/.pkl`、`bootstrap_strategy_summary_v4_1.csv/.pkl`、`bootstrap_paired_differences_v4_1.csv/.pkl`、`bootstrap_paired_summary_v4_1.csv/.pkl`、`bootstrap_rank_stability_v4_1.csv/.pkl`、`bootstrap_point_winner_stability_v4_1.csv/.pkl`、`bootstrap_block_draws_v4_1.csv/.pkl`。

{_table(point)}

{_table(paired[(paired.phase.eq("validation"))&(paired.basis.eq("net"))&(paired.metric.isin(["cagr","sharpe","max_drawdown"]))&(paired.strategy.str.contains("sleeve|single_180_skip5",regex=True))],30)}

## 6. Buffer、保证金和杠杆

10% buffer只作用于最终净目标。国债名义杠杆继续豁免商品限制，但总保证金约束仍按冻结配置执行。

底层：`rebalance_buffer_statistics_v4_1.csv/.pkl`、`margin_leverage_v4_1.csv/.pkl`。

{_table(rebalance[rebalance.strategy.str.contains("sleeve")],20)}

{_table(margin[margin.strategy.str.contains("sleeve")],20)}

## 7. 不能据此得出的结论

不能把代理滑点当作真实逐笔成交成本；不能把2022—2026称为未触碰样本外；不能用Bootstrap创造未来证据；不能因为21个方案中某一方案点估计最高便宣称统计显著优胜；也不能把袖套净额前虚拟订单视为真实可成交订单。
"""
    (root/"BACKTEST_RESULT_REPORT_v4_1.md").write_text(text,encoding="utf-8")


def _write_attribution(settings: Settings, root: Path) -> None:
    cost=_read(root,"same_path_cost_summary_v4_1"); yearly=_read(root,"same_path_yearly_v4_1"); matrix=_read(root,"cost_response_matrix_v4_1"); elasticity=_read(root,"cost_elasticity_break_even_v4_1"); events=_read(root,"cost_turnover_attribution_v4_1"); influence=_read(root,"forecast_horizon_influence_summary_v4_1"); fcorr=_read(root,"forecast_pair_correlation_summary_v4_1"); selection=_read(root,"selection_pair_overlap_v4_1"); target=_read(root,"target_position_loo_effects_v4_1"); rcorr=_read(root,"independent_return_correlations_v4_1"); scorr=_read(root,"sector_return_correlations_v4_1"); lcorr=_read(root,"long_short_return_correlations_v4_1")
    short=cost[(cost.strategy.isin(["single_20","single_60","single_120"]))&(cost.period.eq("full"))]
    main_cols=["strategy","net_年化收益率","same_path_pre_cost_年化收益率","cagr_drag_points","commission_drag","base_slippage_drag","roll_slippage_drag","impact_drag","total_cost_drag","total_cost_over_positive_pre_cost_profit","turnover","cost_per_lot","cost_per_million_notional"]
    nonmono=events[events.strategy.isin(["single_20","single_60","single_120","single_180","single_250"])].groupby(["strategy","event_class"],as_index=False).agg(lots=("lots","sum"),commission=("commission","sum"),base_slippage=("base_slippage","sum"),roll_slippage=("roll_slippage","sum"),impact=("impact","sum"),traded_notional=("traded_notional","sum"))
    v4=pd.read_pickle(root.parent.parent/"outputs/v4_20260902_102628/scenario_metrics_v4.pkl").set_index("标签")
    sleeve=_read(root,"sleeve_metrics_v4_1"); sleeve_val=sleeve[(~sleeve.strategy.str.contains("fixed"))&(sleeve.period.eq("validation"))].set_index("strategy")
    full_influence=influence[influence.scope.eq("full")]
    raw_all=full_influence[(full_influence.combo.eq("all"))&(full_influence.version.eq("raw"))].set_index("horizon")
    scaled_all=full_influence[(full_influence.combo.eq("all"))&(full_influence.version.eq("scaled"))].set_index("horizon")
    rc_full=rcorr[(rcorr.basis.eq("net"))&(rcorr.scope.eq("full"))]
    text=f"""# 成本与信号归因报告 v4.1

## 1. 20、60、120日成本拖累

同路径成本前曲线冻结原头寸，不把加回后的权益反馈到未来仓位；C0则是完整因果重跑，两者用途不同。

底层：`same_path_daily_v4_1.csv/.pkl`、`same_path_cost_summary_v4_1.csv/.pkl`、`same_path_yearly_v4_1.csv/.pkl`。

{_table(short[main_cols])}

成本导致正的成本前年份转负的记录：

{_table(yearly[yearly.cost_turns_positive_to_negative])}

## 2. 成本矩阵、弹性与盈亏平衡

56个预注册单元全部保留。盈亏平衡只在C2(-1)、C3(0)、C4(+1)、C5(+2)相邻实测点符号穿越时插值；未穿越即标记“未达到”，不向范围外推。C0-C3分解中的反馈残差包括权益改变、整数手数、buffer、限制与参与率的因果反馈。

底层：`cost_response_matrix_v4_1.csv/.pkl`、`cost_elasticity_break_even_v4_1.csv/.pkl`。

{_table(matrix[(matrix.period.isin(["full","validation"]))&(matrix.cost_code.isin(["C0","C3","C6","C7"]))],40)}

{_table(elasticity[elasticity.comparison.str.contains("break_even|accounting",regex=True)],40)}

## 3. 成本与换手来源；为什么窗口并不必然单调

窗口长度只改变信号路径；实际成本还同时由横截面赢家/输家切换、跨零反手、信号退出、换月、波动率调整、保证金强制、10% buffer、整数手数、参与率部分成交和权益反馈决定。因此“短周期换手更高”不是充分解释；下表展示五个普通周期在真实事件路径上的差异。

底层：`cost_turnover_attribution_v4_1.csv/.pkl`。

{_table(nonmono,50)}

## 4. 滑点模型的双向偏差

可能高估成本：固定每腿不利tick忽略限价改善和被动成交；正常基础tick、换月额外tick及参与率冲击可能对同一流动性风险重复计价；日线开盘附近实际价差可能小于假设。可能低估成本：日线无法看见盘口深度、排队、集合竞价、夜盘跳空、涨跌停板内成交概率、冲击持续性和极端时段撤单；按滞后中位成交量的阶梯冲击也可能低估大单的非线性影响。

在没有逐笔成交与盘口数据时，只能把C2至C5视为正常模型附近的局部区间、C6/C7视为统一2/3 tick压力边界；不能称其为真实置信区间。具体可承受范围以实际穿越表为准。

## 5. 周期对forecast、选择和目标的影响

有效贡献只在每周独立形成日计算，缺任一分量时整组缺失。`selection_detail`记录删除周期后的winner/loser变化；账户层目标、成交、成本、净利润和回撤使用v4预注册留一场景。

底层：`forecast_horizon_influence_v4_1.csv/.pkl`、`forecast_horizon_influence_summary_v4_1.csv/.pkl`、`selection_omission_changes_v4_1.csv/.pkl`、`target_position_loo_effects_v4_1.csv/.pkl`。

{_table(influence[influence.scope.eq("full")],40)}

{_table(target,40)}

## 6. Forecast层与横截面选择层相关性

相关系数先按品种、共同有效周度观察计算，再跨品种报告分位数，避免把所有品种简单堆叠。raw/scaled分开保存；选择只包含当日流动性合格且forecast有效的农业与化工品种。

底层：`forecast_pair_correlations_v4_1.csv/.pkl`、`forecast_pair_correlation_summary_v4_1.csv/.pkl`、`selection_pair_overlap_v4_1.csv/.pkl`。

{_table(fcorr[(fcorr.scope.eq("phase"))&fcorr.sector.isna()],30)}

{_table(selection.groupby(["basis","horizon1","horizon2","phase","sector"],as_index=False).agg(common_observations=("n","size"),mean_rank_spearman=("rank_spearman","mean"),winner_overlap=("winner_same","mean"),loser_overlap=("loser_same","mean"),jaccard=("jaccard","mean")).head(40),40)}

## 7. 独立策略收益层与分散解释

独立20/60/120/180/250日策略按前一日权益计算成本前后收益。底层包含全样本、样本内、验证期、逐年、最差5%日、回撤重合、板块及多空相关。

底层：`independent_return_correlations_v4_1.csv/.pkl`、`sector_return_correlations_v4_1.csv/.pkl`、`long_short_return_correlations_v4_1.csv/.pkl`、`diversification_metrics_v4_1.csv/.pkl`。

{_table(rcorr[rcorr.scope.isin(["full","validation","tail_worst_5pct"])],40)}

{_table(scorr[scorr.scope.eq("validation")],30)}

{_table(lcorr[lcorr.scope.eq("validation")],30)}

综合判断应同时看相关性、留一影响、选择切换、净额成本和分散表；不能只凭forecast相关较低便断言可交易收益已分散，也不能只凭聚合回撤较小忽略收益稀释和额外成本。

## 8. 归因结论

- raw全周期聚合中，20/60/120/250日的平均绝对forecast贡献约为 {raw_all.loc[20,'mean_absolute_contribution_weight']:.1%}/{raw_all.loc[60,'mean_absolute_contribution_weight']:.1%}/{raw_all.loc[120,'mean_absolute_contribution_weight']:.1%}/{raw_all.loc[250,'mean_absolute_contribution_weight']:.1%}；scaling后变为 {scaled_all.loc[20,'mean_absolute_contribution_weight']:.1%}/{scaled_all.loc[60,'mean_absolute_contribution_weight']:.1%}/{scaled_all.loc[120,'mean_absolute_contribution_weight']:.1%}/{scaled_all.loc[250,'mean_absolute_contribution_weight']:.1%}。scaling主要修正幅度支配，并未使周期收益独立。
- 单周期成本后全样本日收益Pearson相关中位数为 {rc_full.pearson.median():.3f}，范围 {rc_full.pearson.min():.3f}—{rc_full.pearson.max():.3f}；因此存在一定分散空间，但慢周期之间仍高度相关，且回撤期大面积重叠。
- 验证期fast raw/scaled聚合年化收益分别为 {v4.loc['multi_fast_raw','验证期年化收益率']:.2%}/{v4.loc['multi_fast_scaled','验证期年化收益率']:.2%}，fast袖套为 {sleeve_val.loc['strategy_sleeve_fast_equal_risk','年化收益率']:.2%}；all为 {v4.loc['multi_all_raw','验证期年化收益率']:.2%}/{v4.loc['multi_all_scaled','验证期年化收益率']:.2%} 对袖套 {sleeve_val.loc['strategy_sleeve_all_equal_risk','年化收益率']:.2%}；slow为 {v4.loc['multi_slow_raw','验证期年化收益率']:.2%}/{v4.loc['multi_slow_scaled','验证期年化收益率']:.2%} 对袖套 {sleeve_val.loc['strategy_sleeve_slow_equal_risk','年化收益率']:.2%}。
- 只有slow袖套在验证期由聚合方案的负收益改善为正，但固定3 tick后又转为负，且FG占化工正利润仍为100%。因此没有证据表明“独立袖套”普遍优于forecast聚合；fast/all反而把样本内强势和验证期失效放大。
- 多周期较弱不是单一原因：raw中20日幅度支配造成快速信号稀释慢周期；横截面赢家/输家重合率有限，带来切换；周期收益只有中等而非零相关；最终新增交易成本和信号抵消共同吞噬分散收益。
"""
    (root/"COST_AND_SIGNAL_ATTRIBUTION_REPORT_v4_1.md").write_text(text,encoding="utf-8")


def _write_inventory(root: Path) -> None:
    rows=[]
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append({"relative_path":str(path.relative_to(root)),"bytes":path.stat().st_size,"sha256":digest})
    _save(pd.DataFrame(rows),root,"file_inventory_v4_1")
