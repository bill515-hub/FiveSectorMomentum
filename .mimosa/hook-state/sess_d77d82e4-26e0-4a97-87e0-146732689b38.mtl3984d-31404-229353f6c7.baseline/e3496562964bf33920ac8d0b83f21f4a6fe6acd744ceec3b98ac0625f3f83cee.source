from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .analytics_v3 import component_slippage_cost
from .engine import BacktestResult
from .engine_v4 import V4Scenario
from .signals_v4 import ForecastLibraryV4


SECTOR_NAMES = {
    "ferrous": "黑色系", "agriculture": "农产品",
    "chemical_energy": "化工能源", "government_bond": "国债",
    "base_metal": "基本金属",
}


def metrics_from_equity(
    equity: pd.DataFrame, initial_capital: float,
    start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
) -> dict[str, float | int | bool]:
    frame = equity.sort_values("date").copy()
    if start is not None:
        frame = frame[frame["date"] >= pd.Timestamp(start)]
    if end is not None:
        frame = frame[frame["date"] <= pd.Timestamp(end)]
    if frame.empty:
        return _empty_metrics()
    previous = frame["equity"] - frame["net_pnl"]
    returns = frame["net_pnl"].divide(previous.replace(0.0, np.nan)).dropna()
    start_equity = float(previous.iloc[0])
    end_equity = float(frame["equity"].iloc[-1])
    years = len(frame) / 252.0
    annual_return = (end_equity / start_equity) ** (1.0 / years) - 1.0 if start_equity > 0 else np.nan
    annual_vol = float(returns.std(ddof=1) * np.sqrt(252.0)) if len(returns) > 1 else np.nan
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252.0)) if returns.std(ddof=1) > 0 else np.nan
    downside = returns[returns < 0]
    downside_dev = float(np.sqrt((downside.pow(2)).mean()) * np.sqrt(252.0)) if not downside.empty else np.nan
    sortino = float(returns.mean() * 252.0 / downside_dev) if np.isfinite(downside_dev) and downside_dev > 0 else np.nan
    wealth = frame["equity"] / start_equity
    running_peak = wealth.cummax()
    drawdown = wealth / running_peak - 1.0
    max_drawdown = float(drawdown.min())
    trough_position = int(np.argmin(drawdown.to_numpy()))
    peak_position = int(np.argmax(wealth.iloc[:trough_position + 1].to_numpy()))
    peak_value = float(wealth.iloc[peak_position])
    later = wealth.iloc[trough_position + 1:]
    recovered = later.ge(peak_value).any()
    if recovered:
        recovery_position = int(later.ge(peak_value).to_numpy().argmax()) + trough_position + 1
    else:
        recovery_position = len(frame) - 1
    recovery_days = max(0, recovery_position - peak_position)
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else np.nan
    return {
        "年化收益率": float(annual_return), "年化波动率": annual_vol,
        "夏普比率": sharpe, "Sortino比率": sortino,
        "最大回撤": max_drawdown, "回撤恢复交易日": int(recovery_days),
        "最大回撤是否恢复": bool(recovered), "Calmar比率": float(calmar),
        "净利润_元": float(frame["net_pnl"].sum()), "观测日数": int(len(frame)),
    }


def _empty_metrics() -> dict[str, float | int | bool]:
    return {
        "年化收益率": np.nan, "年化波动率": np.nan, "夏普比率": np.nan,
        "Sortino比率": np.nan, "最大回撤": np.nan, "回撤恢复交易日": 0,
        "最大回撤是否恢复": False, "Calmar比率": np.nan,
        "净利润_元": 0.0, "观测日数": 0,
    }


def scenario_metrics_v4(
    results: list[BacktestResult], scenarios: list[V4Scenario],
    initial_capital: float, sample_split: str,
) -> pd.DataFrame:
    scenario_by_name = {scenario.name: scenario for scenario in scenarios}
    split = pd.Timestamp(sample_split)
    rows = []
    for result in results:
        scenario = scenario_by_name[result.scenario.name]
        full = metrics_from_equity(result.equity, initial_capital)
        insample = metrics_from_equity(result.equity, initial_capital, end=split - pd.Timedelta(days=1))
        validation = metrics_from_equity(result.equity, initial_capital, start=split)
        rolling_live = metrics_from_equity(result.equity, initial_capital, start=pd.Timestamp("2020-01-01"))
        fills = result.fills
        duration_years = max(len(result.equity) / 252.0, 1e-12)
        traded_notional = float(fills["traded_notional"].sum()) if not fills.empty else 0.0
        row = {
            "场景": scenario.name, "标签": scenario.label, "实验阶段": scenario.stage,
            "家族": scenario.family, "周期": ",".join(map(str, scenario.horizons)),
            "聚合方式": scenario.aggregation, "跳过近期日数": scenario.skip_recent_days,
            "有效窗口日数": scenario.effective_window_days,
            "是否研究候选": scenario.candidate, "父组合": scenario.parent_label,
            "留一周期": scenario.omitted_horizon,
            "滑点模型": scenario.slippage_model,
            "固定基础滑点_tick": scenario.fixed_slippage_ticks if scenario.slippage_model == "fixed" else np.nan,
        }
        for prefix, metric in [
            ("全样本", full), ("样本内", insample), ("验证期", validation),
            ("滚动下一年拼接", rolling_live),
        ]:
            for key, value in metric.items():
                row[f"{prefix}{key}"] = value
        row.update({
            "成交分段数": int(len(fills)),
            "成交手数": float(fills["quantity"].abs().sum()) if not fills.empty else 0.0,
            "手续费_元": float(fills["commission"].sum()) if not fills.empty else 0.0,
            "交易所手续费_元": float(fills["exchange_commission"].sum()) if not fills.empty else 0.0,
            "滑点成本_元": float(fills["slippage_cost"].sum()) if not fills.empty else 0.0,
            "市场冲击成本_元": component_slippage_cost(fills, "impact_ticks"),
            "换月额外滑点_元": component_slippage_cost(fills, "roll_extra_ticks"),
            "总交易成本_元": float(fills["commission"].sum() + fills["slippage_cost"].sum()) if not fills.empty else 0.0,
            # Keep the frozen v3 reporting definition: traded notional divided
            # by average account equity and annualized by observed trading days.
            "年化名义换手_倍": traded_notional / float(result.equity["equity"].mean()) / duration_years,
            "buffer阻止次数": result.diagnostics.get("buffer_holds", 0),
            "buffer评估次数": result.diagnostics.get("buffer_evaluations", 0),
            "紧急减仓日": result.diagnostics.get("emergency_vol_reduction_days", 0),
            "保证金强制缩减日": result.diagnostics.get("forced_constraint_days", 0),
            "峰值总保证金占用": float(result.equity["margin_utilization"].max()),
            "峰值商品保证金占用": float(result.equity["commodity_margin_utilization"].max()),
            "峰值商品名义杠杆": float(result.equity["commodity_gross_leverage"].max()),
            "峰值国债名义杠杆": float(result.equity["exempt_gross_leverage"].max()),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def yearly_performance_v4(
    result: BacktestResult, scenario_label: str, initial_capital: float, final_date: str,
) -> pd.DataFrame:
    rows = []
    last_year = pd.Timestamp(final_date).year
    for year, frame in result.equity.groupby(result.equity["date"].dt.year):
        metrics = metrics_from_equity(frame, initial_capital)
        rows.append({
            "场景": scenario_label, "年份": int(year), **metrics,
            "是否亏损年": bool(metrics["年化收益率"] < 0),
            "年度状态": "完整年度" if int(year) < last_year else f"截至{final_date}",
        })
    return pd.DataFrame(rows)


def rolling_walk_forward_v4(
    result: BacktestResult, scenario_label: str, initial_capital: float,
    first_train_year: int = 2015, train_years: int = 5,
) -> pd.DataFrame:
    final_year = int(result.equity["date"].dt.year.max())
    rows = []
    for test_year in range(first_train_year + train_years, final_year + 1):
        train = metrics_from_equity(
            result.equity, initial_capital,
            pd.Timestamp(f"{test_year-train_years}-01-01"),
            pd.Timestamp(f"{test_year-1}-12-31"),
        )
        test = metrics_from_equity(
            result.equity, initial_capital,
            pd.Timestamp(f"{test_year}-01-01"), pd.Timestamp(f"{test_year}-12-31"),
        )
        rows.append({
            "场景": scenario_label, "训练起始年": test_year - train_years,
            "训练结束年": test_year - 1, "测试年": test_year,
            "测试年是否完整": test_year < final_year,
            **{f"训练{k}": v for k, v in train.items()},
            **{f"测试{k}": v for k, v in test.items()},
        })
    return pd.DataFrame(rows)


def robustness_v4(
    result: BacktestResult, scenario_label: str, initial_capital: float, sample_split: str,
) -> pd.DataFrame:
    equity = result.equity.sort_values("date").copy()
    fills = result.fills.copy()
    slippage = fills.groupby("date")["slippage_cost"].sum() if not fills.empty else pd.Series(dtype=float)
    equity["slippage"] = equity["date"].map(slippage).fillna(0.0)
    previous = equity["equity"] - equity["net_pnl"]
    equity["net_return"] = equity["net_pnl"] / previous
    equity["pre_cost_return"] = (equity["net_pnl"] + equity["fees"] + equity["slippage"]) / previous
    exclusions = {
        "全部年份": set(), "删除2020年": {2020}, "删除2024年": {2024},
        "同时删除2020和2024年": {2020, 2024},
    }
    split = pd.Timestamp(sample_split)
    periods = {
        "全样本": (None, None), "样本内": (None, split - pd.Timedelta(days=1)),
        "验证期": (split, None), "滚动下一年拼接": (pd.Timestamp("2020-01-01"), None),
    }
    rows = []
    for slice_label, excluded in exclusions.items():
        for period_label, (start, end) in periods.items():
            subset = equity[~equity["date"].dt.year.isin(excluded)].copy()
            if start is not None:
                subset = subset[subset["date"] >= start]
            if end is not None:
                subset = subset[subset["date"] <= end]
            for cost_label, column in [("含成本", "net_return"), ("成本前", "pre_cost_return")]:
                rows.append({
                    "场景": scenario_label, "切片": slice_label, "阶段": period_label,
                    "成本口径": cost_label, **metrics_from_returns_v4(subset[column]),
                })
    return pd.DataFrame(rows)


def metrics_from_returns_v4(returns: pd.Series) -> dict[str, float | int | bool]:
    series = returns.dropna().astype(float)
    if series.empty:
        return _empty_metrics()
    wealth = (1.0 + series).cumprod()
    pseudo = pd.DataFrame({"date": pd.RangeIndex(len(series)), "equity": wealth, "net_pnl": series})
    years = len(series) / 252.0
    annual_return = float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(series.std(ddof=1) * np.sqrt(252.0))
    sharpe = float(series.mean() / series.std(ddof=1) * np.sqrt(252.0)) if series.std(ddof=1) > 0 else np.nan
    downside = series[series < 0]
    downside_dev = float(np.sqrt(downside.pow(2).mean()) * np.sqrt(252.0)) if not downside.empty else np.nan
    sortino = float(series.mean() * 252.0 / downside_dev) if np.isfinite(downside_dev) and downside_dev > 0 else np.nan
    drawdown = wealth / wealth.cummax() - 1.0
    max_dd = float(drawdown.min())
    calmar = annual_return / abs(max_dd) if max_dd < 0 else np.nan
    trough = int(np.argmin(drawdown.to_numpy()))
    peak = int(np.argmax(wealth.iloc[:trough+1].to_numpy()))
    peak_value = float(wealth.iloc[peak])
    later = wealth.iloc[trough+1:]
    recovered = later.ge(peak_value).any()
    recovery = (int(later.ge(peak_value).to_numpy().argmax()) + trough + 1) if recovered else len(wealth)-1
    return {
        "年化收益率": annual_return, "年化波动率": vol, "夏普比率": sharpe,
        "Sortino比率": sortino, "最大回撤": max_dd,
        "回撤恢复交易日": max(0, recovery-peak), "最大回撤是否恢复": bool(recovered),
        "Calmar比率": calmar, "净利润_元": np.nan, "观测日数": len(series),
    }


def pnl_contribution_v4(result: BacktestResult, scenario_label: str, sample_split: str) -> pd.DataFrame:
    pnl = result.pnl_by_instrument.copy()
    fills = result.fills.copy()
    if pnl.empty:
        return pd.DataFrame()
    pnl["date"] = pd.to_datetime(pnl["date"])
    fills["date"] = pd.to_datetime(fills["date"])
    costs = fills.groupby(["date", "contract", "instrument"], as_index=False).agg(
        滑点成本_元=("slippage_cost", "sum"), 手续费核对_元=("commission", "sum")
    )
    pnl = pnl.merge(costs, on=["date", "contract", "instrument"], how="left")
    pnl[["滑点成本_元", "手续费核对_元"]] = pnl[["滑点成本_元", "手续费核对_元"]].fillna(0.0)
    pnl["交易成本前盈亏_元"] = pnl["gross_pnl"] + pnl["滑点成本_元"]
    pnl["方向"] = pnl["position_direction"].map({1: "多头", -1: "空头", 0: "无方向"})
    pnl["阶段"] = np.where(pnl["date"] < pd.Timestamp(sample_split), "样本内", "验证期")
    combined = pd.concat([pnl, pnl.assign(阶段="全样本")], ignore_index=True)
    grouped = combined.groupby(["阶段", "sector", "instrument", "方向"], as_index=False).agg(
        交易成本前盈亏_元=("交易成本前盈亏_元", "sum"),
        滑点成本_元=("滑点成本_元", "sum"), 手续费_元=("commission", "sum"),
        净利润_元=("net_pnl", "sum"),
    )
    grouped["场景"] = scenario_label
    grouped["板块"] = grouped["sector"].map(SECTOR_NAMES)
    return grouped[[
        "场景", "阶段", "板块", "instrument", "方向", "交易成本前盈亏_元",
        "滑点成本_元", "手续费_元", "净利润_元",
    ]]


def concentration_v4(
    result: BacktestResult, scenario_label: str, contribution: pd.DataFrame,
) -> pd.DataFrame:
    yearly = result.equity.assign(年份=result.equity["date"].dt.year).groupby("年份")["net_pnl"].sum()
    full = contribution[contribution["阶段"].eq("全样本")]
    sector = full.groupby("板块")["净利润_元"].sum()
    instrument = full.groupby("instrument")["净利润_元"].sum()
    positive_year = yearly.clip(lower=0.0)
    positive_sector = sector.clip(lower=0.0)
    positive_instrument = instrument.clip(lower=0.0)
    chemical = full[full["板块"].eq("化工能源")].groupby("instrument")["净利润_元"].sum()
    chemical_positive = chemical.clip(lower=0.0)
    fg_profit = float(chemical.get("FG", 0.0))
    return pd.DataFrame([{
        "场景": scenario_label,
        "正盈利年份前两名占比": _top_share(positive_year, 2),
        "年份利润HHI": _hhi(positive_year),
        "2020和2024占累计净利润": float(yearly.reindex([2020, 2024]).fillna(0.0).sum() / yearly.sum()) if yearly.sum() else np.nan,
        "亏损年份数": int((yearly < 0).sum()),
        "单一板块正利润占比": _top_share(positive_sector, 1),
        "板块利润HHI": _hhi(positive_sector),
        "单一品种正利润占比": _top_share(positive_instrument, 1),
        "品种利润HHI": _hhi(positive_instrument),
        "FG净利润_元": fg_profit,
        "化工能源净利润_元": float(chemical.sum()),
        "FG占化工正利润比": float(max(fg_profit, 0.0) / chemical_positive.sum()) if chemical_positive.sum() else np.nan,
    }])


def _top_share(values: pd.Series, count: int) -> float:
    positive = values[values > 0]
    return float(positive.nlargest(count).sum() / positive.sum()) if positive.sum() else np.nan


def _hhi(values: pd.Series) -> float:
    positive = values[values > 0]
    if not positive.sum():
        return np.nan
    weights = positive / positive.sum()
    return float((weights ** 2).sum())


def forecast_distribution_v4(
    library: ForecastLibraryV4, sample_split: str,
) -> pd.DataFrame:
    rows = []
    split = pd.Timestamp(sample_split)
    variants: list[tuple[str, int, pd.DataFrame]] = []
    for horizon in sorted(library.raw_regular):
        variants.extend([
            ("普通原始", horizon, library.raw_regular[horizon]),
            ("普通缩放截断", horizon, library.scaled_regular[horizon]),
            ("跳过5日原始", horizon, library.raw_skip5[horizon]),
        ])
    variants.append(("250减20原始", 250, library.raw_250_minus_20))
    periods = {
        "全样本": (None, None), "样本内": (None, split - pd.Timedelta(days=1)),
        "验证期": (split, None),
    }
    for variant, horizon, frame in variants:
        for period, (start, end) in periods.items():
            sub = frame
            if start is not None:
                sub = sub[sub.index >= start]
            if end is not None:
                sub = sub[sub.index <= end]
            values = sub.stack().dropna()
            rows.append({
                "版本": variant, "周期": horizon, "阶段": period,
                "有效forecast数": len(values), "缺失比例": float(sub.isna().mean().mean()),
                "均值": float(values.mean()) if len(values) else np.nan,
                "平均绝对值": float(values.abs().mean()) if len(values) else np.nan,
                "标准差": float(values.std(ddof=1)) if len(values) > 1 else np.nan,
                "P01": float(values.quantile(.01)) if len(values) else np.nan,
                "P05": float(values.quantile(.05)) if len(values) else np.nan,
                "P50": float(values.quantile(.50)) if len(values) else np.nan,
                "P95": float(values.quantile(.95)) if len(values) else np.nan,
                "P99": float(values.quantile(.99)) if len(values) else np.nan,
                "截断占比": float(values.abs().ge(20.0 - 1e-12).mean()) if "缩放" in variant and len(values) else 0.0,
            })
    return pd.DataFrame(rows)


def scaling_statistics_v4(library: ForecastLibraryV4, sample_split: str) -> pd.DataFrame:
    split = pd.Timestamp(sample_split)
    rows = []
    for horizon, scalar in sorted(library.scalars.items()):
        for phase, values in {
            "全样本": scalar,
            "样本内": scalar[scalar.index < split],
            "验证期": scalar[scalar.index >= split],
        }.items():
            clean = values.dropna()
            rows.append({
                "周期": horizon, "阶段": phase, "首个有效日期": clean.index.min() if len(clean) else pd.NaT,
                "有效日数": len(clean), "平均scale": clean.mean(), "标准差": clean.std(ddof=1),
                "最小值": clean.min(), "P05": clean.quantile(.05), "P50": clean.quantile(.5),
                "P95": clean.quantile(.95), "最大值": clean.max(),
            })
    return pd.DataFrame(rows)


def forecast_correlations_v4(library: ForecastLibraryV4, sample_split: str) -> pd.DataFrame:
    rows = []
    split = pd.Timestamp(sample_split)
    for version, source in [("原始", library.raw_regular), ("缩放截断", library.scaled_regular)]:
        stacked = pd.concat(
            {str(horizon): frame.stack() for horizon, frame in sorted(source.items())}, axis=1
        )
        dates = stacked.index.get_level_values(0)
        for phase, mask in [
            ("全样本", np.ones(len(stacked), dtype=bool)),
            ("样本内", dates < split), ("验证期", dates >= split),
        ]:
            corr = stacked.loc[mask].corr()
            for left in corr.index:
                for right in corr.columns:
                    if int(left) <= int(right):
                        pair = stacked.loc[mask, [left, right]].dropna()
                        rows.append({
                            "版本": version, "阶段": phase, "周期1": int(left), "周期2": int(right),
                            "相关系数": corr.loc[left, right], "共同观测数": len(pair),
                        })
    return pd.DataFrame(rows)


def effective_weights_v4(
    library: ForecastLibraryV4, combinations: dict[str, Iterable[int]], sample_split: str,
) -> pd.DataFrame:
    split = pd.Timestamp(sample_split)
    rows = []
    for combo, horizons_iter in combinations.items():
        horizons = tuple(int(item) for item in horizons_iter)
        for version, source in [("raw", library.raw_regular), ("scaled", library.scaled_regular)]:
            stacked = pd.concat({h: source[h].stack() for h in horizons}, axis=1).dropna()
            denominator = stacked.abs().sum(axis=1).replace(0.0, np.nan)
            weights = stacked.abs().divide(denominator, axis=0)
            dates = weights.index.get_level_values(0)
            for phase, mask in [
                ("全样本", np.ones(len(weights), dtype=bool)),
                ("样本内", dates < split), ("验证期", dates >= split),
            ]:
                for horizon in horizons:
                    values = weights.loc[mask, horizon].dropna()
                    rows.append({
                        "组合": combo, "版本": version, "阶段": phase, "周期": horizon,
                        "名义权重": 1.0 / len(horizons),
                        "平均绝对forecast有效贡献权重": values.mean() if len(values) else np.nan,
                        "有效观测数": len(values),
                    })
    return pd.DataFrame(rows)


def marginal_pnl_v4(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    diagnostics = metrics[metrics["父组合"].notna() & metrics["留一周期"].notna()]
    for _, omitted in diagnostics.iterrows():
        parent = metrics[metrics["标签"].eq(omitted["父组合"])]
        if parent.empty:
            continue
        parent_row = parent.iloc[0]
        row = {
            "组合": omitted["父组合"], "留一场景": omitted["标签"],
            "周期": int(omitted["留一周期"]),
        }
        for phase in ["全样本", "样本内", "验证期", "滚动下一年拼接"]:
            row[f"{phase}边际净利润_元"] = (
                float(parent_row[f"{phase}净利润_元"]) - float(omitted[f"{phase}净利润_元"])
            )
        rows.append(row)
    return pd.DataFrame(rows)
