from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from five_sector_momentum.analytics import sector_contribution
from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.engine import BacktestResult, BacktestScenario
from five_sector_momentum.reports import write_engine_report, write_result_report
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import SignalBundle
from five_sector_momentum.storage import read_frame, read_json


def _load_signals(run_root: Path) -> SignalBundle:
    return SignalBundle(
        scores=read_frame(run_root / "scores"),
        daily_price_vol=read_frame(run_root / "daily_price_vol"),
        eligibility=read_frame(run_root / "eligibility"),
        liquidity=read_frame(run_root / "liquidity"),
        selections=read_frame(run_root / "selections"),
        directions=read_frame(run_root / "directions"),
        diagnostics=read_json(run_root / "signal_diagnostics.json"),
    )


def _load_reference_result(run_root: Path) -> BacktestResult:
    scenario = BacktestScenario(0.275, "cancel_recalculate", 2.0)
    root = run_root / scenario.name
    return BacktestResult(
        scenario=scenario,
        equity=read_frame(root / "daily_equity"),
        positions=read_frame(root / "positions"),
        targets=read_frame(root / "targets"),
        orders=read_frame(root / "orders"),
        fills=read_frame(root / "fills"),
        rejections=read_frame(root / "rejections"),
        pnl_by_instrument=read_frame(root / "pnl_by_instrument"),
        diagnostics=read_json(root / "diagnostics.json"),
    )


def _write_quality_audit(data, run_root: Path) -> None:
    mapped = data.mapping.merge(
        data.bars,
        left_on=["date", "contract"], right_on=["date", "ts_code"],
        how="left", suffixes=("_mapping", "_bar"),
    )
    panama = data.diagnostics.get("panama", {})
    checks = [
        ("标准化真实合约日线行数", len(data.bars), "信息"),
        ("主力映射行数", len(data.mapping), "信息"),
        ("复权价格行数", len(data.adjusted_prices), "信息"),
        ("主力映射找不到真实合约日线", int(mapped["ts_code"].isna().sum()), "应为0"),
        ("映射合约收盘价缺失或非正", int((mapped["close"].isna() | mapped["close"].le(0)).sum()), "应为0"),
        ("映射合约成交量为零或缺失", int((mapped["volume"].isna() | mapped["volume"].le(0)).sum()), "应为0"),
        ("结算价缺失且使用收盘价回退", int((mapped["settlement"].isna() & mapped["close"].notna()).sum()), "披露"),
        ("主力映射重复键", int(data.mapping.duplicated(["date", "instrument"]).sum()), "应为0"),
        ("复权价格重复键", int(data.adjusted_prices.duplicated(["date", "instrument"]).sum()), "应为0"),
        ("Panama换月次数", int(panama.get("roll_count", 0)), "信息"),
        ("Panama拼接失败", len(panama.get("stitch_failures", [])), "应为0"),
    ]
    pd.DataFrame(checks, columns=["检查项", "数量", "判定口径"]).to_csv(
        run_root / "data_quality_audit_v2.csv", index=False, encoding="utf-8-sig"
    )


def _write_correlation_audit(data, run_root: Path) -> None:
    prices = data.adjusted_prices.pivot(
        index="date", columns="instrument", values="adjusted_price"
    ).sort_index()
    changes = prices.diff()
    normalized = changes.divide(changes.rolling(60, min_periods=40).std(ddof=1))
    groups = {
        "农产品": ["C", "M", "P", "JD", "LH", "CF", "SR", "AP"],
        "化工能源": ["FG", "MA", "UR", "RU", "SP", "SC"],
    }
    pair_rows = []
    summary_rows = []
    for sector, instruments in groups.items():
        corr = normalized[instruments].corr(min_periods=252)
        values = []
        for i, left in enumerate(instruments):
            for right in instruments[i + 1:]:
                value = corr.loc[left, right]
                pair_rows.append({"板块": sector, "品种1": left, "品种2": right, "相关系数": value})
                if pd.notna(value):
                    values.append(abs(float(value)))
        summary_rows.append({
            "板块": sector, "品种数": len(instruments),
            "平均绝对相关系数": float(np.mean(values)),
            "最大绝对相关系数": float(np.max(values)),
        })
    pd.DataFrame(pair_rows).to_csv(
        run_root / "pairwise_correlation_audit_v2.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(summary_rows).to_csv(
        run_root / "correlation_summary_v2.csv", index=False, encoding="utf-8-sig"
    )


def _configure_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _write_charts(result: BacktestResult, run_root: Path, initial_capital: float) -> None:
    _configure_chinese_font()
    equity = result.equity.copy().sort_values("date")
    equity["累计净值"] = equity["equity"] / initial_capital
    equity["回撤"] = equity["equity"] / equity["equity"].cummax() - 1.0
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(equity["date"], equity["累计净值"], color="#2457A7", linewidth=1.5)
    axes[0].set_title("v2基准情景：累计净值（27.5%目标、2 tick、取消并重算）")
    axes[0].set_ylabel("累计净值")
    axes[0].grid(alpha=0.25)
    axes[1].fill_between(equity["date"], equity["回撤"], 0, color="#C94C4C", alpha=0.7)
    axes[1].set_ylabel("回撤")
    axes[1].set_xlabel("日期")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(run_root / "equity_drawdown_v2.png", dpi=160)
    plt.close(fig)

    yearly = pd.read_csv(run_root / "yearly_performance_reference.csv")
    colors = np.where(yearly["年化收益率"] >= 0, "#2C8C69", "#C94C4C")
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(yearly["年份"].astype(str), yearly["年化收益率"] * 100, color=colors)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("v2基准情景：分年度年化收益率")
    ax.set_ylabel("收益率（%）")
    ax.set_xlabel("年份")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(run_root / "yearly_returns_v2.png", dpi=160)
    plt.close(fig)

    sector = pd.read_csv(run_root / "sector_contribution_reference.csv")
    pivot = sector.pivot(index="板块", columns="阶段", values="净利润_元") / 1_000_000
    order = [item for item in ["农产品", "化工能源", "黑色系", "国债", "基本金属"] if item in pivot.index]
    pivot = pivot.reindex(order)
    columns = [item for item in ["样本内（2015-2021）", "验证期（2022-2026）"] if item in pivot]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    pivot[columns].plot(kind="bar", ax=ax, color=["#4C78A8", "#F58518"][:len(columns)])
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("v2基准情景：板块净利润贡献")
    ax.set_ylabel("净利润（百万元）")
    ax.set_xlabel("板块")
    ax.tick_params(axis="x", rotation=0)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(run_root / "sector_contribution_v2.png", dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/five_sector_momentum_v2.yaml")
    parser.add_argument("--run-root", default="outputs/v2_20260901_213543")
    args = parser.parse_args()
    settings = Settings.load(args.config)
    run_root = Path(args.run_root).resolve()
    data = load_bundle(settings)
    signals = _load_signals(run_root)
    result = _load_reference_result(run_root)
    summary = pd.read_csv(run_root / "scenario_summary.csv")
    initial_capital = float(settings.section("run")["initial_capital"])

    sector_contribution(result, initial_capital, settings.section("run")["sample_split"]).to_csv(
        run_root / "sector_contribution_reference.csv", index=False, encoding="utf-8-sig"
    )
    _write_quality_audit(data, run_root)
    _write_correlation_audit(data, run_root)
    _write_charts(result, run_root, initial_capital)
    write_engine_report(settings, run_root / "BACKTEST_ENGINE_AUDIT_v2.md", data)
    write_result_report(settings, data, signals, summary, run_root / "BACKTEST_RESULT_REPORT_v2.md")


if __name__ == "__main__":
    main()
