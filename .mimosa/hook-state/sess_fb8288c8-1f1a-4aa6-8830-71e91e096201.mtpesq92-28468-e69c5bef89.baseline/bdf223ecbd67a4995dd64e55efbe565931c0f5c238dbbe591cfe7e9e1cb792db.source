from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .analytics import performance_metrics, yearly_performance
from .engine import BacktestResult


SECTOR_NAMES = {
    "ferrous": "黑色系", "agriculture": "农产品",
    "chemical_energy": "化工能源", "government_bond": "国债",
    "base_metal": "基本金属", "unknown": "未知",
}


def scenario_parameter_table(results: list[BacktestResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        scenario = result.scenario
        rows.append({
            "场景": scenario.name, "标签": scenario.label, "实验阶段": scenario.stage,
            "目标波动率": scenario.annual_vol_target,
            "客户手续费倍数": scenario.fee_multiplier,
            "滑点模型": scenario.slippage_model,
            "固定基础滑点_tick": scenario.fixed_slippage_ticks if scenario.slippage_model == "fixed" else np.nan,
            "调仓模式": scenario.rebalance_mode, "buffer比例": scenario.buffer_fraction,
            "紧急波动率阈值": scenario.emergency_vol_ratio,
            "未成交处理": scenario.unfilled_mode,
        })
    return pd.DataFrame(rows)


def scenario_metrics_v3(
    results: list[BacktestResult], initial_capital: float, sample_split: str
) -> pd.DataFrame:
    split = pd.Timestamp(sample_split)
    rows = []
    for result in results:
        scenario = result.scenario
        row: dict[str, Any] = {
            "场景": scenario.name, "标签": scenario.label, "实验阶段": scenario.stage,
            "手续费倍数": scenario.fee_multiplier, "滑点模型": scenario.slippage_model,
            "固定滑点_tick": scenario.fixed_slippage_ticks if scenario.slippage_model == "fixed" else np.nan,
            "调仓模式": scenario.rebalance_mode, "buffer比例": scenario.buffer_fraction,
            "紧急阈值": scenario.emergency_vol_ratio,
        }
        for prefix, start, end in [
            ("全样本", None, None),
            ("样本内", None, split - pd.Timedelta(days=1)),
            ("验证期", split, None),
        ]:
            metrics = performance_metrics(result, initial_capital, start=start, end=end)
            row.update({
                f"{prefix}年化收益率": metrics.get("annual_return", np.nan),
                f"{prefix}年化波动率": metrics.get("annual_volatility", np.nan),
                f"{prefix}夏普比率": metrics.get("sharpe", np.nan),
                f"{prefix}最大回撤": metrics.get("max_drawdown", np.nan),
            })
        fills = result.fills
        row.update({
            "全样本净利润_元": float(result.equity["equity"].iloc[-1] - initial_capital),
            "成交分段数": len(fills),
            "成交手数": float(fills["quantity"].abs().sum()) if not fills.empty else 0.0,
            "手续费_元": float(fills["commission"].sum()) if not fills.empty else 0.0,
            "交易所手续费_元": float(fills["exchange_commission"].sum()) if not fills.empty else 0.0,
            "滑点成本_元": float(fills["slippage_cost"].sum()) if not fills.empty else 0.0,
            "市场冲击成本_元": component_slippage_cost(fills, "impact_ticks"),
            "换月额外滑点_元": component_slippage_cost(fills, "roll_extra_ticks"),
            "年化名义换手_倍": _annual_turnover(result),
            "拒单及部分成交事件": len(result.rejections),
            "峰值总保证金占用": float(result.equity["margin_utilization"].max()),
            "峰值商品保证金占用": float(result.equity["commodity_margin_utilization"].max()),
            "峰值商品名义杠杆": float(result.equity["commodity_gross_leverage"].max()),
            "峰值国债名义杠杆": float(result.equity["exempt_gross_leverage"].max()),
            "buffer阻止次数": int(result.diagnostics.get("buffer_holds", 0)),
            "buffer评估次数": int(result.diagnostics.get("buffer_evaluations", 0)),
            "紧急减仓日": int(result.diagnostics.get("emergency_vol_reduction_days", 0)),
            "保证金强制缩减日": int(result.diagnostics.get("forced_constraint_days", 0)),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def component_slippage_cost(fills: pd.DataFrame, tick_column: str) -> float:
    if fills.empty or tick_column not in fills:
        return 0.0
    total_ticks = fills["total_slippage_ticks"].replace(0.0, np.nan)
    return float((fills["slippage_cost"] * fills[tick_column] / total_ticks).fillna(0.0).sum())


def cost_attribution(result: BacktestResult, instrument_meta: pd.DataFrame) -> pd.DataFrame:
    if result.fills.empty:
        return pd.DataFrame()
    fills = result.fills.copy()
    sector = instrument_meta.set_index("instrument")["sector"].to_dict()
    fills["板块"] = fills["instrument"].map(sector).map(SECTOR_NAMES)
    fills["基础滑点成本_元"] = _component_series(fills, "base_slippage_ticks")
    fills["换月额外滑点_元"] = _component_series(fills, "roll_extra_ticks")
    fills["市场冲击成本_元"] = _component_series(fills, "impact_ticks")
    fills["代理费用成交"] = fills["fee_is_proxy"].astype(int)
    return (
        fills.groupby(["板块", "instrument", "reason", "transaction_type"], as_index=False)
        .agg(
            成交分段数=("quantity", "size"), 成交手数=("quantity", lambda value: value.abs().sum()),
            交易所手续费_元=("exchange_commission", "sum"), 客户手续费_元=("commission", "sum"),
            基础滑点成本_元=("基础滑点成本_元", "sum"),
            换月额外滑点_元=("换月额外滑点_元", "sum"),
            市场冲击成本_元=("市场冲击成本_元", "sum"),
            总滑点成本_元=("slippage_cost", "sum"),
            代理费用成交分段数=("代理费用成交", "sum"),
            成交名义金额_元=("traded_notional", "sum"),
        )
    )


def _component_series(fills: pd.DataFrame, column: str) -> pd.Series:
    denominator = fills["total_slippage_ticks"].replace(0.0, np.nan)
    return (fills["slippage_cost"] * fills[column] / denominator).fillna(0.0)


def pnl_contribution(
    result: BacktestResult, initial_capital: float, sample_split: str
) -> pd.DataFrame:
    if result.pnl_by_instrument.empty:
        return pd.DataFrame()
    pnl = result.pnl_by_instrument.copy()
    fills = result.fills.copy()
    fills["date"] = pd.to_datetime(fills["date"])
    cost = (
        fills.groupby(["date", "contract", "instrument"], as_index=False)
        .agg(滑点成本_元=("slippage_cost", "sum"), 手续费核对_元=("commission", "sum"))
    )
    pnl["date"] = pd.to_datetime(pnl["date"])
    pnl = pnl.merge(cost, on=["date", "contract", "instrument"], how="left")
    pnl[["滑点成本_元", "手续费核对_元"]] = pnl[["滑点成本_元", "手续费核对_元"]].fillna(0.0)
    pnl["交易成本前盈亏_元"] = pnl["gross_pnl"] + pnl["滑点成本_元"]
    pnl["方向"] = pnl.get("position_direction", 0).map({1: "多头", -1: "空头", 0: "无方向"})
    pnl["阶段"] = np.where(
        pnl["date"] < pd.Timestamp(sample_split), "样本内（2015-2021）", "验证期（2022-2026）"
    )
    combined = pd.concat([pnl, pnl.assign(阶段="全样本")], ignore_index=True)
    grouped = combined.groupby(["阶段", "sector", "instrument", "方向"], as_index=False).agg(
        交易成本前盈亏_元=("交易成本前盈亏_元", "sum"),
        滑点成本_元=("滑点成本_元", "sum"), 手续费_元=("commission", "sum"),
        净利润_元=("net_pnl", "sum"),
    )
    grouped["板块"] = grouped["sector"].map(SECTOR_NAMES)
    grouped["相对初始资金贡献"] = grouped["净利润_元"] / initial_capital
    return grouped[[
        "阶段", "板块", "instrument", "方向", "交易成本前盈亏_元",
        "滑点成本_元", "手续费_元", "净利润_元", "相对初始资金贡献",
    ]]


def rolling_walk_forward(
    result: BacktestResult, initial_capital: float, first_train_year: int = 2015,
    train_years: int = 5,
) -> pd.DataFrame:
    final_year = int(result.equity["date"].dt.year.max())
    rows = []
    for test_year in range(first_train_year + train_years, final_year + 1):
        train_start = test_year - train_years
        train = performance_metrics(
            result, initial_capital, pd.Timestamp(f"{train_start}-01-01"),
            pd.Timestamp(f"{test_year - 1}-12-31"),
        )
        test = performance_metrics(
            result, initial_capital, pd.Timestamp(f"{test_year}-01-01"),
            pd.Timestamp(f"{test_year}-12-31"),
        )
        rows.append({
            "训练起始年": train_start, "训练结束年": test_year - 1,
            "测试年": test_year, "测试年是否完整": test_year < final_year,
            "训练年化收益率": train.get("annual_return", np.nan),
            "训练夏普比率": train.get("sharpe", np.nan),
            "测试年化收益率": test.get("annual_return", np.nan),
            "测试夏普比率": test.get("sharpe", np.nan),
            "测试最大回撤": test.get("max_drawdown", np.nan),
        })
    return pd.DataFrame(rows)


def robustness_slices(
    result: BacktestResult, initial_capital: float, sample_split: str
) -> pd.DataFrame:
    equity = result.equity.sort_values("date").copy()
    fills = result.fills.copy()
    slippage_by_date = fills.groupby("date")["slippage_cost"].sum() if not fills.empty else pd.Series(dtype=float)
    equity["slippage"] = equity["date"].map(slippage_by_date).fillna(0.0)
    previous_equity = equity["equity"] - equity["net_pnl"]
    equity["net_return"] = equity["net_pnl"] / previous_equity
    equity["pre_cost_return"] = (equity["net_pnl"] + equity["fees"] + equity["slippage"]) / previous_equity
    definitions = {
        "全部年份": set(), "删除2020年": {2020}, "删除2024年": {2024},
        "同时删除2020和2024年": {2020, 2024},
    }
    periods = {
        "全样本": (None, None), "样本内": (None, pd.Timestamp(sample_split) - pd.Timedelta(days=1)),
        "验证期": (pd.Timestamp(sample_split), None),
    }
    rows = []
    for label, excluded in definitions.items():
        for period, (start, end) in periods.items():
            subset = equity[~equity["date"].dt.year.isin(excluded)]
            if start is not None:
                subset = subset[subset["date"] >= start]
            if end is not None:
                subset = subset[subset["date"] <= end]
            for cost_label, column in [("含成本", "net_return"), ("成本前", "pre_cost_return")]:
                metric = metrics_from_returns(subset[column])
                rows.append({"切片": label, "阶段": period, "成本口径": cost_label, **metric})
    return pd.DataFrame(rows)


def metrics_from_returns(returns: pd.Series) -> dict[str, float]:
    series = returns.dropna().astype(float)
    if series.empty:
        return {"年化收益率": np.nan, "年化波动率": np.nan, "夏普比率": np.nan, "最大回撤": np.nan}
    years = len(series) / 252.0
    wealth = (1.0 + series).cumprod()
    annual_return = wealth.iloc[-1] ** (1.0 / years) - 1.0
    annual_vol = series.std(ddof=1) * math.sqrt(252)
    sharpe = series.mean() / series.std(ddof=1) * math.sqrt(252) if series.std(ddof=1) > 0 else np.nan
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "年化收益率": float(annual_return), "年化波动率": float(annual_vol),
        "夏普比率": float(sharpe), "最大回撤": float(drawdown.min()),
    }


def margin_leverage_summary(result: BacktestResult) -> pd.DataFrame:
    equity = result.equity
    return pd.DataFrame([{
        "平均总保证金占用": equity["margin_utilization"].mean(),
        "峰值总保证金占用": equity["margin_utilization"].max(),
        "平均商品保证金占用": equity["commodity_margin_utilization"].mean(),
        "峰值商品保证金占用": equity["commodity_margin_utilization"].max(),
        "平均商品名义杠杆": equity["commodity_gross_leverage"].mean(),
        "峰值商品名义杠杆": equity["commodity_gross_leverage"].max(),
        "平均国债名义杠杆": equity["exempt_gross_leverage"].mean(),
        "峰值国债名义杠杆": equity["exempt_gross_leverage"].max(),
        "实际总保证金超目标日数": result.diagnostics.get("actual_total_margin_breach_days", 0),
        "实际商品保证金超目标日数": result.diagnostics.get("actual_commodity_margin_breach_days", 0),
        "保证金强制缩减日数": result.diagnostics.get("forced_constraint_days", 0),
    }])


def _annual_turnover(result: BacktestResult) -> float:
    years = max(len(result.equity) / 252.0, 1 / 252.0)
    return float(result.fills["traded_notional"].sum() / result.equity["equity"].mean() / years)


def yearly_table(result: BacktestResult, initial_capital: float, end_date: str) -> pd.DataFrame:
    table = yearly_performance(result, initial_capital)
    final_year = pd.Timestamp(end_date).year
    table["年度状态"] = np.where(table["年份"].eq(final_year), f"截至{end_date}", "完整年度")
    return table
