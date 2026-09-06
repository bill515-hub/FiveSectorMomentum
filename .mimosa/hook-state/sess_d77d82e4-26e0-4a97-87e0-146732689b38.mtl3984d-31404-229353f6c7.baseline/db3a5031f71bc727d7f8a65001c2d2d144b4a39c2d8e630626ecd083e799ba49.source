from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .engine import BacktestResult


def performance_metrics(
    result: BacktestResult, initial_capital: float, start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    equity = result.equity.copy()
    fills = result.fills.copy()
    if start is not None:
        equity = equity[equity["date"] >= start]
        if not fills.empty:
            fills = fills[fills["date"] >= start]
    if end is not None:
        equity = equity[equity["date"] <= end]
        if not fills.empty:
            fills = fills[fills["date"] <= end]
    if equity.empty:
        return {"observations": 0}
    series = equity.set_index("date")["equity"].astype(float)
    first_base = initial_capital if start is None else float(series.iloc[0] - equity.iloc[0]["net_pnl"])
    returns = pd.concat([pd.Series([equity.iloc[0]["net_pnl"] / first_base], index=[series.index[0]]), series.pct_change().dropna()])
    years = max(len(returns) / 252.0, 1 / 252.0)
    total_return = series.iloc[-1] / first_base - 1.0
    annual_return = (series.iloc[-1] / first_base) ** (1.0 / years) - 1.0 if series.iloc[-1] > 0 else -1.0
    annual_vol = returns.std(ddof=1) * math.sqrt(252)
    sharpe = returns.mean() / returns.std(ddof=1) * math.sqrt(252) if returns.std(ddof=1) > 0 else np.nan
    downside = returns[returns < 0].std(ddof=1) * math.sqrt(252)
    sortino = returns.mean() * 252 / downside if downside and downside > 0 else np.nan
    drawdown_base = pd.concat([
        pd.Series([first_base], index=[series.index[0] - pd.Timedelta(nanoseconds=1)]),
        series,
    ])
    drawdown = drawdown_base / drawdown_base.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else np.nan
    return {
        "observations": int(len(returns)),
        "start": str(series.index[0].date()), "end": str(series.index[-1].date()),
        "ending_equity": float(series.iloc[-1]), "total_return": float(total_return),
        "annual_return": float(annual_return), "annual_volatility": float(annual_vol),
        "sharpe": float(sharpe), "sortino": float(sortino),
        "max_drawdown": max_drawdown, "calmar": float(calmar),
        "total_fees": float(equity["fees"].sum()),
        "total_slippage_cost": float(fills.get("slippage_cost", pd.Series(dtype=float)).sum()),
        "annual_turnover": float(
            fills.get("traded_notional", pd.Series(dtype=float)).sum()
            / max(float(series.mean()), 1.0) / years
        ),
        "average_margin_utilization": float(equity["margin_utilization"].mean()),
        "maximum_margin_utilization": float(equity["margin_utilization"].max()),
        "average_gross_leverage": float(equity["gross_leverage"].mean()),
        "maximum_gross_leverage": float(equity["gross_leverage"].max()),
        "maximum_commodity_margin_utilization": float(
            equity.get("commodity_margin_utilization", pd.Series([np.nan])).max()
        ),
        "maximum_commodity_gross_leverage": float(
            equity.get("commodity_gross_leverage", pd.Series([np.nan])).max()
        ),
        "maximum_exempt_gross_leverage": float(
            equity.get("exempt_gross_leverage", pd.Series([np.nan])).max()
        ),
    }


def scenario_summary(
    results: list[BacktestResult], initial_capital: float, sample_split: str
) -> pd.DataFrame:
    split = pd.Timestamp(sample_split)
    rows = []
    for result in results:
        full = performance_metrics(result, initial_capital)
        insample = performance_metrics(result, initial_capital, end=split - pd.Timedelta(days=1))
        outsample = performance_metrics(result, initial_capital, start=split)
        row = {
            "scenario": result.scenario.name,
            "vol_target": result.scenario.annual_vol_target,
            "unfilled_mode": result.scenario.unfilled_mode,
            "slippage_ticks": result.scenario.slippage_ticks,
        }
        for prefix, metrics in [("full", full), ("is", insample), ("oos", outsample)]:
            for key in [
                "annual_return", "annual_volatility", "sharpe", "max_drawdown", "total_fees",
                "total_slippage_cost", "annual_turnover", "maximum_margin_utilization",
                "maximum_commodity_margin_utilization", "maximum_commodity_gross_leverage",
                "maximum_exempt_gross_leverage",
            ]:
                row[f"{prefix}_{key}"] = metrics.get(key, np.nan)
        row["fills"] = len(result.fills)
        row["rejections"] = len(result.rejections)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["vol_target", "slippage_ticks", "unfilled_mode"]).reset_index(drop=True)


def selection_summary(selections: pd.DataFrame) -> pd.DataFrame:
    if selections.empty:
        return pd.DataFrame()
    summary = (
        selections.assign(side=np.where(selections["direction"] > 0, "long", "short"))
        .groupby(["sector", "instrument", "side"], as_index=False)
        .agg(selection_weeks=("signal_date", "count"), average_score=("score", "mean"),
             first_selected=("signal_date", "min"), last_selected=("signal_date", "max"))
    )
    return summary.sort_values(["sector", "selection_weeks"], ascending=[True, False])


def yearly_performance(result: BacktestResult, initial_capital: float) -> pd.DataFrame:
    years = sorted(result.equity["date"].dt.year.unique())
    rows = []
    for year in years:
        metrics = performance_metrics(
            result, initial_capital,
            start=pd.Timestamp(f"{year}-01-01"), end=pd.Timestamp(f"{year}-12-31"),
        )
        rows.append({"年份": int(year), "年化收益率": metrics.get("annual_return", np.nan),
                     "年化波动率": metrics.get("annual_volatility", np.nan),
                     "夏普比率": metrics.get("sharpe", np.nan),
                     "最大回撤": metrics.get("max_drawdown", np.nan)})
    return pd.DataFrame(rows)


def sector_contribution(
    result: BacktestResult, initial_capital: float, sample_split: str
) -> pd.DataFrame:
    if result.pnl_by_instrument.empty:
        return pd.DataFrame()
    pnl = result.pnl_by_instrument.copy()
    # Execution slippage is embedded in gross_pnl because fills are booked at
    # the slipped execution price.  Add it back to expose a true pre-cost PnL,
    # then show slippage and commission separately for an auditable bridge to
    # net PnL.
    if result.fills.empty or "slippage_cost" not in result.fills.columns:
        pnl["slippage_cost"] = 0.0
    else:
        slippage = (
            result.fills.assign(date=pd.to_datetime(result.fills["date"]))
            .groupby(["date", "instrument", "contract"], as_index=False)["slippage_cost"].sum()
        )
        pnl["date"] = pd.to_datetime(pnl["date"])
        pnl = pnl.merge(slippage, on=["date", "instrument", "contract"], how="left")
        pnl["slippage_cost"] = pnl["slippage_cost"].fillna(0.0)
    pnl["pre_cost_pnl"] = pnl["gross_pnl"] + pnl["slippage_cost"]
    pnl["阶段"] = np.where(
        pnl["date"] < pd.Timestamp(sample_split), "样本内（2015-2021）", "验证期（2022-2026）"
    )
    all_rows = pnl.assign(阶段="全样本")
    combined = pd.concat([pnl, all_rows], ignore_index=True)
    grouped = combined.groupby(["阶段", "sector"], as_index=False).agg(
        交易成本前盈亏_元=("pre_cost_pnl", "sum"),
        滑点成本_元=("slippage_cost", "sum"),
        手续费_元=("commission", "sum"),
        净利润_元=("net_pnl", "sum"),
    )
    totals = grouped.groupby("阶段")["净利润_元"].transform("sum")
    grouped["净利润占组合比例"] = grouped["净利润_元"].divide(totals.replace(0.0, np.nan))
    grouped["相对初始资金贡献"] = grouped["净利润_元"] / initial_capital
    sector_names = {
        "ferrous": "黑色系", "agriculture": "农产品", "chemical_energy": "化工能源",
        "government_bond": "国债", "base_metal": "基本金属", "unknown": "未知",
    }
    grouped["板块"] = grouped["sector"].map(sector_names).fillna(grouped["sector"])
    return grouped[["阶段", "板块", "交易成本前盈亏_元", "滑点成本_元", "手续费_元", "净利润_元",
                    "净利润占组合比例", "相对初始资金贡献"]]
