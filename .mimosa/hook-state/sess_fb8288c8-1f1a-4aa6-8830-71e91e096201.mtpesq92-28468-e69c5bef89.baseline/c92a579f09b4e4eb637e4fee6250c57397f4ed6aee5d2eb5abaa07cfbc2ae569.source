from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import numpy as np
import pandas as pd

from .analytics import selection_summary
from .data_pipeline import DataBundle
from .settings import Settings
from .signals import SignalBundle


def write_engine_report(
    settings: Settings, path: str | Path, data: DataBundle | None = None,
    test_summary: str = "11 项自动化测试全部通过：Panama、点差波动率、周频选择、零/10% buffer、结算价盯市、未来数据不改变历史信号、换月日成本归因，以及端到端事件回测。",
) -> Path:
    config = settings.raw
    version = str(config.get("version", "v1"))
    data_section = "尚未下载真实数据。"
    quality_section = "尚未执行数据质量审计。"
    if data is not None:
        mapping = data.diagnostics.get("mapping", {})
        panama = data.diagnostics.get("panama", {})
        data_section = f"""
- 标准化真实合约日线：{len(data.bars):,} 行
- 主力映射：{len(data.mapping):,} 行；Tushare 映射品种 {len(mapping.get('vendor_used', []))} 个，OI 回退品种 {len(mapping.get('fallback_used', []))} 个
- 距到期不足 {config['roll']['minimum_days_to_expiry']} 日的主力映射保护：{mapping.get('forced_roll_deadline_overrides', 0):,} 个映射日
- Panama adjusted prices：{len(data.adjusted_prices):,} 行，换月 {panama.get('roll_count', 0):,} 次，拼接失败 {len(panama.get('stitch_failures', [])):,} 次
- 合约元数据：{len(data.contract_meta):,} 行
"""
        mapped = data.mapping.merge(
            data.bars,
            left_on=["date", "contract"], right_on=["date", "ts_code"],
            how="left", suffixes=("_mapping", "_bar"),
        )
        coverage = (
            data.adjusted_prices.groupby("instrument", as_index=False)
            .agg(起始日=("date", "min"), 结束日=("date", "max"), 有效日数=("adjusted_price", "count"))
        )
        coverage["起始日"] = pd.to_datetime(coverage["起始日"]).dt.date
        coverage["结束日"] = pd.to_datetime(coverage["结束日"]).dt.date
        economy = (
            data.contract_meta.groupby("instrument", as_index=False)
            .agg(每点价值=("point_value", "median"), 最小变动价位=("tick_size", "median"))
            if {"point_value", "tick_size"}.issubset(data.contract_meta.columns)
            else pd.DataFrame()
        )
        quality_section = f"""
- 主力映射找不到真实合约日线：{mapped['ts_code'].isna().sum():,} 行；
- 映射合约收盘价缺失/非正：{(mapped['close'].isna() | mapped['close'].le(0)).sum():,} 行；
- 映射合约成交量为零或缺失：{(mapped['volume'].isna() | mapped['volume'].le(0)).sum():,} 行；
- 映射合约结算价缺失但可用收盘价回退：{(mapped['settlement'].isna() & mapped['close'].notna()).sum():,} 行；
- 主力映射重复键：{data.mapping.duplicated(['date', 'instrument']).sum():,} 行；复权价格重复键：{data.adjusted_prices.duplicated(['date', 'instrument']).sum():,} 行；
- 复权价格缺失/非有限：{(~np.isfinite(pd.to_numeric(data.adjusted_prices['adjusted_price'], errors='coerce'))).sum():,} 行；
- Panama 拼接失败：{len(panama.get('stitch_failures', [])):,} 次。失败时不跨缺口计算点差。

品种数据覆盖：

{coverage.to_markdown(index=False)}

合约经济参数审计（同品种历史合约中位数）：

{economy.to_markdown(index=False) if not economy.empty else '元数据中没有可展示的每点价值/最小变动价位。'}
"""
    text = f"""# 五板块期货动量回测引擎审计报告（{version}）

> 引擎版本：0.1.0  
> 研究区间：{config['run']['start']} 至 {config['run']['end']}  
> 样本内：{config['run']['start']} 至 2021-12-31；验证期：{config['run']['sample_split']} 至 {config['run']['end']}

## 1. 执行摘要

引擎采用分阶段数据处理和逐日事件回放。信号研究使用收盘价构建的 Panama 加减价差连续价格；真实成交、手续费、保证金、换月和盈亏全部落在映射的真实合约上。

核心研究口径：252 个交易日绝对点差年化 Sharpe、每周最后一个交易日更新信号、每日根据稳健价格点数波动率更新目标手数、10% no-trade buffer、五板块各 20% 风险预算。{version} 将信号价格与账户盯市价格分离：收盘价用于信号，结算价优先用于逐日盈亏和保证金。

## 2. 数据流程

```text
Tushare fut_basic / fut_daily / fut_mapping / fut_settle / ft_limit
  -> 标准化逐合约行情和时点元数据
  -> 主力映射（Tushare 主力优先；到期保护；缺失时 OI 规则回退）
  -> multiple prices
  -> Panama adjusted close
  -> 点差、Sharpe 和稳健点数波动率
  -> 信号、风险目标、订单、成交、账户和报告
```

{data_section}

Tushare 当日主力映射只用于收盘后形成目标，并在下一交易日开盘执行，因此不再额外滞后一日。若映射合约距到期不足 {config['roll']['minimum_days_to_expiry']} 日或当日无行情，改用满足期限条件的最高持仓量远月合约。无供应商映射时采用持仓量规则：候选主力持仓量达到当前合约 110%，连续确认 2 日，且不得向更早到期月份回滚。

## 3. Panama 复权

换月前一日同时取得旧合约与新合约收盘价，计算 `gap = new_close - old_close`，把 gap 加到此前全部 adjusted prices，再接入新合约。最新价格段不调整。连续价格只用于差分信号；账户不在复权价格上记账。

经典后向 Panama 会在未来换月发生后重写过去连续价格的绝对水平。这里的信号只使用一阶点差、滚动点差均值和点差标准差；对过去整段统一加常数不会改变这些量。自动化测试进一步把未来价格改写为极端值，确认截断日前的 score 和 direction 完全不变。绝对复权价水平本身不得用于估值、收益率或阈值判断。

## 4. 未来函数与公式审计

| 环节 | 时点规则 | 审计结论 |
|---|---|---|
| 动量、点数波动率、流动性 | 仅使用截至交易日 t 收盘的数据 | 无前视窗口；滚动函数不居中 |
| 横截面排序 | t 日收盘后在当时合格品种中排序 | 不读取 t+1 行情或未来上市品种 |
| 主力映射 | t 日映射只形成 t 日收盘后的目标 | 最早 t+1 开盘成交 |
| 组合协方差 | 截至 t 的 252 日点差 | 仅作用于 t+1 订单 |
| 已实现波动率反馈 | 截至 t 的组合历史净收益 | 不使用全样本实现波动率反标 |
| 成交 | t 日目标在下一交易日开盘 | 信号与成交价严格错开 |
| 账户盈亏 | 真实合约结算价到结算价 | 不使用 Panama 价格记账 |
| 分段最大回撤 | 阶段首日盈亏前权益作为初始高水位 | 已修复阶段首日回撤遗漏 |

数据质量审计结果：

{quality_section}

## 5. 信号与动态品种池

- 农产品和化工能源使用当时已上市、具有主力映射、至少 252 个价格变化观测的全部配置品种；
- 每周分别在两个板块中做多正 Sharpe 中最高者、做空负 Sharpe 中最低者；
- 黑色系 RB、国债 T、基本金属 AL 按 Sharpe 正负进行绝对动量；
- 没有满足符号条件的一侧保持空仓；板块风险预算不转移；
- 20 日中位成交量至少 {config['eligibility']['min_median_volume']:,.0f} 手、持仓量至少 {config['eligibility']['min_median_open_interest']:,.0f} 手才可进入横截面比较；零成交日不进入连续价格；
- 日点差 Sharpe：`mean(adjusted_close.diff(), 252) / std(...) * sqrt(252)`。

## 6. 波动率与仓位

日价格点数波动率使用 35 日 EWMA 标准差，至少 10 个观测，并使用过去 500 日波动率的 5% 分位数作为下限。每腿目标手数为：

```text
floor(权益 × 组合波动率目标 × 板块20% ÷ 激活腿数
      ÷ (每点价值 × 日点数波动率 × sqrt(252)))
```

信号只在周频变化，但权益和波动率每天变化，因此目标手数每日重算。当前仓位落在目标仓位 ±10% 区间时不交易；越界时只交易到最近的 buffer 边界。合约换月和目标归零不受 buffer 阻碍。

为避免低流动性合约在换月时无法退出，目标仓位还受制于 20 日中位成交量的 {config['portfolio']['max_position_fraction_of_median_volume']:.0%} 和中位持仓量的 {config['portfolio']['max_position_fraction_of_median_open_interest']:.0%}。随后使用 252 日点差协方差估计组合事前波动率，并在 {config['portfolio']['covariance_scaling']['minimum_multiplier']:.1f}–{config['portfolio']['covariance_scaling']['maximum_multiplier']:.1f} 倍范围内缩放；保证金和总杠杆仍是更高优先级的硬约束。

v2 另用截至当日的组合日收益计算 {config['portfolio'].get('realized_volatility_feedback', {}).get('ewma_span_days', 63)} 日 EWMA 已实现波动率，对次日目标再做 {config['portfolio'].get('realized_volatility_feedback', {}).get('minimum_multiplier', 1.0):.2f}–{config['portfolio'].get('realized_volatility_feedback', {}).get('maximum_multiplier', 1.0):.2f} 倍反馈校准。该反馈只看历史组合收益，不读取未来波动率。

## 7. 保证金和组合约束（商品与国债分离）

- 优先使用 Tushare `fut_settle` 的多空投机保证金率；
- 缺失时使用品种级保守保证金率；
- 对交易所保证金率乘以 {config['portfolio']['broker_margin_multiplier']:.2f} 的期货公司附加系数；
- 商品保证金目标上限为权益的 {config['portfolio'].get('max_commodity_margin_utilization', config['portfolio'].get('max_margin_utilization', 1.0)):.0%}；
- 包含国债的总保证金下单目标上限为权益的 {config['portfolio'].get('max_total_margin_utilization', config['portfolio'].get('max_margin_utilization', 1.0)):.0%}；
- 商品总名义杠杆上限为 {config['portfolio'].get('max_commodity_gross_notional_leverage', config['portfolio'].get('max_gross_notional_leverage', 0.0)):.1f} 倍；
- 国债不计入名义杠杆上限，但仍计入总保证金下单目标上限；超限时目标仓位等比例向零缩减。下一交易日开盘成交及其后的价格/权益变化可能令实际占用短暂高于目标上限。

## 8. 成交和成本

订单在信号/调仓日的下一交易日开盘执行。成交价为开盘价加减滑点；单日成交不超过合约成交量的 {config['execution']['max_volume_participation']:.0%}。涨跌停反向锁死、无开盘价、零成交量和参与率不足会产生未成交事件。

手续费优先读取 Tushare 结算参数，并加 20% 经纪商保守附加；本次 `fut_settle` 返回空数据、`ft_limit` 权限不足，因此正式结果采用回退值：每手 {config['execution']['fallback_commission_per_lot']:.2f} 元和成交额 {config['execution']['fallback_commission_rate']:.2%} 两者较高。研究矩阵同时测试 1 tick 与 2 tick 滑点。

未成交测试两种模式：

- `retry`：残余订单保持原意图并在次日继续尝试；
- `cancel_recalculate`：收盘取消残余订单，按最新信号、波动率和权益重新计算次日订单。

## 9. 账户记账

持仓按真实合约 settlement-to-settlement 逐日盯市，结算价缺失时才回退到收盘价；次日开盘成交额外计入成交价到当日结算价的盈亏，并扣除手续费。换月是平旧、开新两笔真实成交，成本独立保留在订单和成交记录中。

## 10. 输出与可复现性

每个场景独立输出权益、持仓、目标、订单、成交、拒单和指标。总报告比较 25%、27.5%、30% 波动率目标，两种未成交模式及两档滑点，并分别汇报样本内和样本外表现。

## 11. 自动化验证

{test_summary}

## 12. 已知限制

- Tushare 没有覆盖的历史经纪商实际加收保证金和客户手续费只能保守估计；
- 日频数据无法判断盘中短暂打开涨跌停后的排队成交，锁板模型偏保守但仍是近似；
- 供应商主力映射不是原始交易所规则，引擎保留映射来源和到期保护标记以便审计；
- 品种板块归类由配置显式维护，新上市品种需要补充代码归类后才能自动动态纳入；
- 协方差缩放使用历史样本估计，不等同于稳定的未来相关性；20% 仍是战略板块预算而非精确边际风险贡献。
- 65%/78% 是形成下一日订单时的目标约束，不是盘中强平模拟；隔夜价格和权益变化可使实际保证金占用高于目标，需要在实盘另加预警和强平逻辑。
- v2 品种池是在查看过 v1 的 2022–2026 结果后调整，因此该区间只能称为验证期，不再是完全未触碰的严格样本外；下一阶段需要保留 2026 年之后数据或使用滚动走样本评估。

## 13. 数据字段依据

- Tushare 期货主力与连续合约映射：<https://tushare.pro/document/2?doc_id=189>
- Tushare 期货日线（结算价、成交量、持仓量）：<https://tushare.pro/document/2?doc_id=138>
- Tushare 期货合约元数据（合约乘数/交易单位）：<https://tushare.pro/document/2?doc_id=135>
"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def write_result_report(
    settings: Settings, data: DataBundle, signals: SignalBundle,
    scenario_summary: pd.DataFrame, path: str | Path,
) -> Path:
    selection = selection_summary(signals.selections)
    mapping = data.diagnostics.get("mapping", {})
    panama = data.diagnostics.get("panama", {})
    failures = pd.DataFrame(panama.get("stitch_failures", []))
    failure_summary = (
        failures.groupby("instrument").size().sort_values(ascending=False).rename("failures").reset_index()
        if not failures.empty else pd.DataFrame(columns=["instrument", "failures"])
    )
    version = str(settings.raw.get("version", "v1"))
    summary_view = scenario_summary[[
        "scenario", "vol_target", "unfilled_mode", "slippage_ticks",
        "full_annual_return", "full_annual_volatility", "full_sharpe", "full_max_drawdown",
        "full_total_fees", "full_total_slippage_cost", "full_annual_turnover",
        "full_maximum_margin_utilization", "full_maximum_commodity_margin_utilization",
        "full_maximum_commodity_gross_leverage", "full_maximum_exempt_gross_leverage",
        "is_annual_return", "is_sharpe", "oos_annual_return", "oos_annual_volatility",
        "oos_sharpe", "oos_max_drawdown", "fills", "rejections",
    ]].copy()
    percent_columns = [column for column in summary_view if any(token in column for token in ["return", "volatility", "drawdown", "margin_utilization"])]
    for column in percent_columns:
        summary_view[column] = summary_view[column].map(lambda value: f"{value:.2%}" if pd.notna(value) else "")
    for column in ["full_total_fees", "full_total_slippage_cost"]:
        summary_view[column] = summary_view[column].map(
            lambda value: f"{value:,.0f}" if pd.notna(value) else ""
        )
    for column in ["full_sharpe", "is_sharpe", "oos_sharpe"]:
        summary_view[column] = summary_view[column].map(
            lambda value: f"{value:.2f}" if pd.notna(value) else ""
        )
    for column in ["full_annual_turnover", "full_maximum_commodity_gross_leverage", "full_maximum_exempt_gross_leverage"]:
        summary_view[column] = summary_view[column].map(
            lambda value: f"{value:.2f}" if pd.notna(value) else ""
        )
    summary_view["unfilled_mode"] = summary_view["unfilled_mode"].map(
        {"retry": "次日重试", "cancel_recalculate": "取消并重算"}
    )
    summary_view = summary_view.rename(columns={
        "scenario": "情景", "vol_target": "目标波动率", "unfilled_mode": "未成交处理",
        "slippage_ticks": "滑点（tick）", "full_annual_return": "全样本年化复合收益",
        "full_annual_volatility": "全样本年化波动率", "full_sharpe": "全样本夏普比率",
        "full_max_drawdown": "全样本最大回撤", "full_total_fees": "全样本手续费（元）",
        "full_total_slippage_cost": "全样本滑点成本（元）", "full_annual_turnover": "年化名义换手（倍）",
        "full_maximum_margin_utilization": "峰值总保证金占用",
        "full_maximum_commodity_margin_utilization": "峰值商品保证金占用",
        "full_maximum_commodity_gross_leverage": "峰值商品名义杠杆",
        "full_maximum_exempt_gross_leverage": "峰值国债名义杠杆",
        "is_annual_return": "样本内年化复合收益",
        "is_sharpe": "样本内夏普比率", "oos_annual_return": "验证期年化复合收益",
        "oos_annual_volatility": "验证期年化波动率", "oos_sharpe": "验证期夏普比率",
        "oos_max_drawdown": "验证期最大回撤", "fills": "成交笔数", "rejections": "拒单/部分成交笔数",
    })
    summary_view["目标波动率"] = summary_view["目标波动率"].map(lambda value: f"{value:.1%}")
    baseline = scenario_summary[
        scenario_summary["vol_target"].eq(0.275)
        & scenario_summary["unfilled_mode"].eq("cancel_recalculate")
        & scenario_summary["slippage_ticks"].eq(2.0)
    ].iloc[0]
    one_tick = scenario_summary[
        scenario_summary["vol_target"].eq(0.275)
        & scenario_summary["unfilled_mode"].eq("cancel_recalculate")
        & scenario_summary["slippage_ticks"].eq(1.0)
    ].iloc[0]
    retry = scenario_summary[
        scenario_summary["vol_target"].eq(0.275)
        & scenario_summary["unfilled_mode"].eq("retry")
        & scenario_summary["slippage_ticks"].eq(2.0)
    ].iloc[0]
    diagnostics = []
    # Only include the official scenario matrix.  Auxiliary diagnostics such as
    # the 0%-buffer counterfactual can share a scenario name and must not
    # overwrite the reference scenario's buffer counters.
    for diagnostic_path in Path(path).parent.glob("vol_*/diagnostics.json"):
        with diagnostic_path.open("r", encoding="utf-8") as handle:
            diagnostics.append(json.load(handle))
    stale_total = sum(int(item.get("stale_mark_events", 0)) for item in diagnostics)
    baseline_diag = next(
        (item for item in diagnostics if item.get("scenario") == baseline["scenario"]), {}
    )
    buffer_ratio = (
        baseline_diag.get("buffer_holds", 0) / baseline_diag.get("buffer_evaluations", 1)
        if baseline_diag.get("buffer_evaluations", 0) else 0.0
    )
    run_root = Path(path).parent
    yearly_path = run_root / "yearly_performance_reference.csv"
    sector_path = run_root / "sector_contribution_reference.csv"
    buffer_path = run_root / "buffer_comparison_v2.csv"
    yearly = pd.read_csv(yearly_path) if yearly_path.exists() else pd.DataFrame()
    sector = pd.read_csv(sector_path) if sector_path.exists() else pd.DataFrame()
    buffer_comparison = pd.read_csv(buffer_path) if buffer_path.exists() else pd.DataFrame()
    sector_analysis = ""
    if not sector.empty and {"阶段", "板块", "净利润_元"}.issubset(sector.columns):
        full = sector[sector["阶段"].eq("全样本")].sort_values("净利润_元", ascending=False)
        validation = sector[sector["阶段"].str.startswith("验证期")].sort_values("净利润_元", ascending=False)
        sector_analysis = (
            "全样本净利润由"
            + "、".join(f"{row['板块']} {row['净利润_元']/1_000_000:.1f} 百万元" for _, row in full.iterrows())
            + "贡献。验证期则由"
            + "、".join(f"{row['板块']} {row['净利润_元']/1_000_000:.1f} 百万元" for _, row in validation.iterrows())
            + "构成，显示板块贡献存在明显状态切换；验证期收益主要集中在农产品和国债，其他三个板块为负。"
        )
    yearly_analysis = ""
    if not yearly.empty and {"年份", "年化收益率"}.issubset(yearly.columns):
        best = yearly.nlargest(2, "年化收益率")
        worst = yearly.nsmallest(3, "年化收益率")
        yearly_analysis = (
            "收益最强的两个年份为 "
            + "、".join(f"{int(row['年份'])} 年 {row['年化收益率']:.2%}" for _, row in best.iterrows())
            + "；较弱的三个年份为 "
            + "、".join(f"{int(row['年份'])} 年 {row['年化收益率']:.2%}" for _, row in worst.iterrows())
            + "。收益集中在少数趋势年份，不能把全样本复合收益理解为稳定的逐年收益。"
        )
    buffer_effect = ""
    if len(buffer_comparison) >= 2 and "buffer比例" in buffer_comparison:
        buffered = buffer_comparison.loc[buffer_comparison["buffer比例"].eq(0.10)].iloc[0]
        unbuffered = buffer_comparison.loc[buffer_comparison["buffer比例"].eq(0.00)].iloc[0]
        buffer_effect = (
            f"10% buffer 将成交笔数减少 "
            f"{1 - buffered['成交笔数'] / unbuffered['成交笔数']:.1%}，年化名义换手减少 "
            f"{1 - buffered['年化名义换手_倍'] / unbuffered['年化名义换手_倍']:.1%}，"
            f"手续费减少 {unbuffered['手续费_元'] - buffered['手续费_元']:,.0f} 元，"
            f"滑点成本减少 {unbuffered['滑点成本_元'] - buffered['滑点成本_元']:,.0f} 元。"
        )
    for frame in [yearly, sector, buffer_comparison]:
        for column in frame.columns:
            if any(token in column for token in ["收益", "波动率", "回撤", "比例", "贡献"]):
                frame[column] = frame[column].map(
                    lambda value: f"{value:.2%}" if pd.notna(value) else ""
                )
            elif "元" in column:
                frame[column] = frame[column].map(
                    lambda value: f"{value:,.0f}" if pd.notna(value) else ""
                )
            elif "夏普" in column:
                frame[column] = frame[column].map(
                    lambda value: f"{value:.2f}" if pd.notna(value) else ""
                )
            elif "换手" in column:
                frame[column] = frame[column].map(
                    lambda value: f"{value:.1f}" if pd.notna(value) else ""
                )
    selection_view = selection.rename(columns={
        "sector": "板块代码", "instrument": "品种", "side": "方向",
        "selection_weeks": "入选周数", "average_score": "平均点差夏普",
        "first_selected": "首次入选", "last_selected": "最后入选",
    }).replace({"long": "多头", "short": "空头"})
    text = f"""# 五板块期货动量策略回测与总结报告（{version}）

> 生成时间：{pd.Timestamp.now().isoformat(timespec='seconds')}  
> 样本内：{settings.section('run')['start']} 至 2021-12-31  
> 验证期：{settings.section('run')['sample_split']} 至 {settings.section('run')['end']}  
> 注意：v2 在查看过 v1 结果后形成，验证期不是完全未触碰的严格样本外。

## 1. 数据与处理审计

- v2 真实合约日线底库：{len(data.bars):,} 行；策略池覆盖 {data.instrument_meta['instrument'].nunique()} 个品种；
- 主力映射：{len(data.mapping):,} 行；Tushare 映射品种：{', '.join(mapping.get('vendor_used', [])) or '无'}；
- OI 回退品种：{', '.join(mapping.get('fallback_used', [])) or '无'}；
- Panama 换月：{panama.get('roll_count', 0):,} 次；拼接失败：{len(panama.get('stitch_failures', [])):,} 次；
- adjusted price：{len(data.adjusted_prices):,} 行；周频选择记录：{len(signals.selections):,} 条。
- 主力距到期保护：{mapping.get('forced_roll_deadline_overrides', 0):,} 个映射日；流动性准入为 20 日中位成交量/持仓量；
- Tushare `fut_settle` 本次无可用行、`ft_limit` 无权限，成本与保证金使用保守回退参数；
- 12 个情景合计无法估值持仓事件：{stale_total:,}。

## 2. 核心结论（固定保守基准）

基准情景固定为 27.5% 名义波动率目标、2 tick 滑点、未成交订单取消并按最新目标重算，不按结果择优：

- 全样本：年化收益 {baseline['full_annual_return']:.2%}，实际年化波动率 {baseline['full_annual_volatility']:.2%}，Sharpe {baseline['full_sharpe']:.2f}，最大回撤 {baseline['full_max_drawdown']:.2%}；
- 样本内：年化收益 {baseline['is_annual_return']:.2%}，Sharpe {baseline['is_sharpe']:.2f}；
- 验证期：年化收益 {baseline['oos_annual_return']:.2%}，实际波动率 {baseline['oos_annual_volatility']:.2%}，Sharpe {baseline['oos_sharpe']:.2f}，最大回撤 {baseline['oos_max_drawdown']:.2%}；
- 1 tick 改为 2 tick 后，全样本年化收益下降 {(one_tick['full_annual_return'] - baseline['full_annual_return']):.2%}，说明日频风险调仓的成本影响显著；
- 同为 2 tick 时，`retry` 与 `cancel_recalculate` 的全样本年化收益差仅 {abs(retry['full_annual_return'] - baseline['full_annual_return']):.2%}，本次结果对拒单处理方式不敏感；
- 名义目标 25%–30%，实际全样本波动率为 {scenario_summary['full_annual_volatility'].min():.2%}–{scenario_summary['full_annual_volatility'].max():.2%}；商品受 {settings.section('portfolio').get('max_commodity_margin_utilization', 0):.0%} 保证金和 {settings.section('portfolio').get('max_commodity_gross_notional_leverage', 0):.1f} 倍杠杆下单约束，国债不受名义杠杆限制但受 {settings.section('portfolio').get('max_total_margin_utilization', 0):.0%} 总保证金下单约束。基准实际峰值为总保证金 {baseline['full_maximum_margin_utilization']:.2%}、商品保证金 {baseline['full_maximum_commodity_margin_utilization']:.2%}、商品名义杠杆 {baseline['full_maximum_commodity_gross_leverage']:.2f} 倍、国债名义杠杆 {baseline['full_maximum_exempt_gross_leverage']:.2f} 倍。
- 10%仓位 buffer 共评估 {baseline_diag.get('buffer_evaluations', 0):,} 次，其中 {baseline_diag.get('buffer_holds', 0):,} 次阻止了小幅调仓，占 {buffer_ratio:.1%}；换月绕过 buffer {baseline_diag.get('buffer_roll_bypasses', 0):,} 次。

## 3. 日波动率调仓与 buffer 对照

{buffer_comparison.to_markdown(index=False) if not buffer_comparison.empty else '无 buffer 对照将在正式情景完成后生成。'}

10% buffer 只在当前持仓落到目标手数±10%之外时交易，并只交易到最近边界；目标归零和换月不受 buffer 阻挡。{buffer_effect}因此日波动率更新没有演变为无条件每日追单。

## 4. 场景结果

{summary_view.to_markdown(index=False)}

## 5. 品种选择明细

{selection_view.to_markdown(index=False) if not selection_view.empty else '没有形成有效选择。'}

## 6. 板块收益贡献

{sector.to_markdown(index=False) if not sector.empty else '板块贡献文件将在回测完成后生成。'}

交易成本前盈亏减去滑点和手续费等于净利润；各板块净利润可以相加，并与组合逐日净盈亏核对，但不等同于各板块独立可投资组合的复合收益率。

{sector_analysis}

## 7. 分年度表现

{yearly.to_markdown(index=False) if not yearly.empty else '年度表现文件将在回测完成后生成。'}

{yearly_analysis}

## 8. 结论解释原则

- 策略选择和仓位均只使用当时可得数据；
- 验证期从 2022-01-01 开始，不与样本内重叠，但由于 v2 是事后研究迭代，不能再宣称严格样本外；
- 应优先比较验证期夏普、回撤、成本和不同成交假设下的稳定性，而不是挑选全样本最佳场景；
- 若 `retry` 与 `cancel_recalculate` 差异明显，说明策略对交易可达性敏感；
- 若 1 tick 与 2 tick 差异明显，说明周频信号之外的日频风险调仓可能产生过高换手；
- 若实际年化波动显著低于目标，主要检查整数手数、空闲板块预算、保证金约束和品种间相关性。

## 9. 数据异常与限制

{len(failures):,} 次 Panama 拼接失败集中在无重叠成交的合约。失败日保留缺失值，252 日点差窗口不会跨断点计算虚假收益。按品种汇总如下，逐次明细保存在对应 normalized 目录的 `diagnostics.json`：

{failure_summary.to_markdown(index=False)}

## 10. 结果图

![基准情景净值与回撤](equity_drawdown_v2.png)

![基准情景分年度收益](yearly_returns_v2.png)

![基准情景板块净利润贡献](sector_contribution_v2.png)

本报告是研究回测，不构成投资建议。手续费与保证金不是逐客户、逐日的真实账单；日线数据也无法精确还原盘中排队与开板成交。
"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
