from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from .analytics import performance_metrics
from .analytics_v3 import (
    cost_attribution, margin_leverage_summary, pnl_contribution,
    rolling_walk_forward, robustness_slices, scenario_metrics_v3,
    scenario_parameter_table, yearly_table,
)
from .costs_v3 import FeeSchedule
from .data_pipeline import load_bundle
from .engine import BacktestResult
from .engine_v3 import BacktestEngineV3, BacktestScenarioV3
from .settings import Settings
from .signals import build_signals
from .storage import read_frame, write_frame, write_json


def core_v3_scenarios() -> list[BacktestScenarioV3]:
    """Pre-registered single-factor sequence; deliberately not a Cartesian product."""
    return [
        BacktestScenarioV3("formal_baseline", "00_formal"),
        # Stage 1A: fee multiplier, v2-like daily/fixed-2-tick reference.
        BacktestScenarioV3("fee_1p2", "01_fee", fee_multiplier=1.2, slippage_model="fixed", rebalance_mode="daily"),
        BacktestScenarioV3("cost_reference_fee_1p5_fixed_2", "01_fee", slippage_model="fixed", rebalance_mode="daily"),
        BacktestScenarioV3("fee_2p0", "01_fee", fee_multiplier=2.0, slippage_model="fixed", rebalance_mode="daily"),
        # Stage 1B: fixed and liquidity-aware slippage with fee fixed at 1.5.
        BacktestScenarioV3("fixed_1_tick", "02_slippage", slippage_model="fixed", fixed_slippage_ticks=1.0, rebalance_mode="daily"),
        BacktestScenarioV3("fixed_3_tick", "02_slippage", slippage_model="fixed", fixed_slippage_ticks=3.0, rebalance_mode="daily"),
        BacktestScenarioV3("normal_slippage_daily", "02_slippage", slippage_model="normal", rebalance_mode="daily"),
        BacktestScenarioV3("stress_slippage_daily", "02_slippage", slippage_model="stress", rebalance_mode="daily"),
        # Stage 2: rebalance schedule; normal slippage and fee 1.5 are fixed.
        BacktestScenarioV3("weekly", "03_rebalance", rebalance_mode="weekly"),
        BacktestScenarioV3("hybrid_threshold_110", "03_rebalance", emergency_vol_ratio=1.10),
        BacktestScenarioV3("hybrid_threshold_130", "03_rebalance", emergency_vol_ratio=1.30),
        # Stage 3: buffer; formal hybrid 120% otherwise fixed.
        BacktestScenarioV3("buffer_0", "04_buffer", buffer_fraction=0.00),
        BacktestScenarioV3("buffer_5", "04_buffer", buffer_fraction=0.05),
        BacktestScenarioV3("buffer_15", "04_buffer", buffer_fraction=0.15),
        BacktestScenarioV3("buffer_20", "04_buffer", buffer_fraction=0.20),
        # Stage 4: three pre-defined cross-pressure points only.
        BacktestScenarioV3("fee_2_normal", "05_cross_stress", fee_multiplier=2.0),
        BacktestScenarioV3("fee_1p5_stress", "05_cross_stress", slippage_model="stress"),
        BacktestScenarioV3("fee_2_stress", "05_cross_stress", fee_multiplier=2.0, slippage_model="stress"),
    ]


def run_v3_research(settings: Settings) -> Path:
    if settings.raw.get("version") != "v3":
        raise ValueError("run_v3_research requires a v3 config")
    data = load_bundle(settings)
    signals = build_signals(settings, data)
    project = settings.path.parent.parent
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    run_root = project / "outputs" / f"v3_{timestamp}"
    run_root.mkdir(parents=True, exist_ok=False)

    fee_path = _project_path(project, settings.section("fees")["rules_path"])
    fee_schedule = FeeSchedule.load(fee_path)
    fee_rules = read_frame(fee_path)
    engine = BacktestEngineV3(settings, data, signals, fee_schedule)
    _save_common_inputs(run_root, signals, fee_rules, project)

    results: list[BacktestResult] = []
    identities: set[tuple] = set()
    for scenario in core_v3_scenarios():
        _run_unique(engine, scenario, run_root, results, identities)

    # Cost break-even uses formal hybrid/10% buffer and changes one cost axis at
    # a time. Stop after both requested zero crossings have actual neighboring points.
    tick_cross_full = False
    tick_cross_validation = False
    for tick in range(1, int(settings.section("v3_research")["break_even_max_ticks"]) + 1):
        scenario = BacktestScenarioV3(
            f"break_even_tick_{tick}", "06_break_even_tick",
            slippage_model="fixed", fixed_slippage_ticks=float(tick),
        )
        result = _run_unique(engine, scenario, run_root, results, identities)
        if result is None:
            continue
        tick_cross_full |= result.equity["equity"].iloc[-1] <= float(settings.section("run")["initial_capital"])
        validation = performance_metrics(
            result, float(settings.section("run")["initial_capital"]),
            start=pd.Timestamp(settings.section("run")["sample_split"]),
        )
        tick_cross_validation |= validation.get("sharpe", np.nan) <= 0
        if tick_cross_full and tick_cross_validation:
            break

    fee_multipliers = list(settings.section("v3_research")["break_even_fee_multipliers"])
    for extra in [20.0, 40.0, 80.0]:
        if extra not in fee_multipliers:
            fee_multipliers.append(extra)
    fee_cross_full = False
    fee_cross_validation = False
    for multiplier in sorted(fee_multipliers):
        scenario = BacktestScenarioV3(
            f"break_even_fee_{str(multiplier).replace('.', 'p')}", "07_break_even_fee",
            fee_multiplier=float(multiplier),
        )
        result = _run_unique(engine, scenario, run_root, results, identities)
        if result is None:
            continue
        fee_cross_full |= result.equity["equity"].iloc[-1] <= float(settings.section("run")["initial_capital"])
        validation = performance_metrics(
            result, float(settings.section("run")["initial_capital"]),
            start=pd.Timestamp(settings.section("run")["sample_split"]),
        )
        fee_cross_validation |= validation.get("sharpe", np.nan) <= 0
        if fee_cross_full and fee_cross_validation:
            break

    initial_capital = float(settings.section("run")["initial_capital"])
    sample_split = settings.section("run")["sample_split"]
    parameters = scenario_parameter_table(results)
    metrics = scenario_metrics_v3(results, initial_capital, sample_split)
    _write_both(parameters, run_root / "scenario_parameters_v3")
    _write_both(metrics, run_root / "scenario_metrics_v3")
    break_even = break_even_table(metrics)
    _write_both(break_even, run_root / "cost_break_even_v3")

    baseline = next(item for item in results if item.scenario.label == "formal_baseline")
    _write_both(
        yearly_table(baseline, initial_capital, settings.section("run")["end"]),
        run_root / "yearly_performance_baseline_v3",
    )
    _write_both(cost_attribution(baseline, data.instrument_meta), run_root / "cost_attribution_baseline_v3")
    _write_both(
        pnl_contribution(baseline, initial_capital, sample_split),
        run_root / "pnl_contribution_baseline_v3",
    )
    _write_both(rolling_walk_forward(baseline, initial_capital), run_root / "rolling_walk_forward_v3")
    _write_both(
        robustness_slices(baseline, initial_capital, sample_split),
        run_root / "robustness_slices_v3",
    )
    _write_both(margin_leverage_summary(baseline), run_root / "margin_leverage_baseline_v3")
    _write_both(_buffer_rebalance_stats(results), run_root / "rebalance_buffer_statistics_v3")
    _write_both(_v2_comparison(project, metrics), run_root / "v2_v3_comparison")
    _write_both(_fee_data_summary(project), run_root / "fee_data_coverage_summary_v3")

    write_json({
        "version": "v3", "run_id": timestamp, "config": str(settings.path),
        "formal_baseline": baseline.scenario.name, "scenario_count": len(results),
        "output": str(run_root), "v2_output_modified": False,
    }, run_root / "manifest.json")

    from .reports_v3 import write_engine_audit_v3, write_result_report_v3, write_v3_charts
    write_v3_charts(run_root, baseline, metrics)
    write_engine_audit_v3(settings, data, run_root)
    write_result_report_v3(settings, run_root)
    return run_root


def _run_unique(
    engine: BacktestEngineV3, scenario: BacktestScenarioV3, run_root: Path,
    results: list[BacktestResult], identities: set[tuple],
) -> BacktestResult | None:
    identity = (
        scenario.annual_vol_target, scenario.unfilled_mode, scenario.fee_multiplier,
        scenario.slippage_model, scenario.fixed_slippage_ticks if scenario.slippage_model == "fixed" else None,
        scenario.rebalance_mode, scenario.buffer_fraction, scenario.emergency_vol_ratio,
    )
    if identity in identities:
        return None
    identities.add(identity)
    result = engine.run(scenario)
    results.append(result)
    root = run_root / scenario.name
    for name, frame in [
        ("daily_equity", result.equity), ("positions", result.positions),
        ("targets", result.targets), ("orders", result.orders), ("fills", result.fills),
        ("rejections", result.rejections), ("pnl_by_instrument", result.pnl_by_instrument),
    ]:
        write_frame(frame, root / name)
    write_json(result.diagnostics, root / "diagnostics.json")
    write_json({
        "label": scenario.label, "stage": scenario.stage,
        "annual_vol_target": scenario.annual_vol_target,
        "fee_multiplier": scenario.fee_multiplier, "slippage_model": scenario.slippage_model,
        "fixed_slippage_ticks": scenario.fixed_slippage_ticks,
        "rebalance_mode": scenario.rebalance_mode, "buffer_fraction": scenario.buffer_fraction,
        "emergency_vol_ratio": scenario.emergency_vol_ratio,
        "unfilled_mode": scenario.unfilled_mode,
    }, root / "scenario_parameters.json")
    print(f"completed {scenario.name}", flush=True)
    return result


def _save_common_inputs(run_root: Path, signals, fee_rules: pd.DataFrame, project: Path) -> None:
    for name, frame in [
        ("scores", signals.scores), ("daily_price_vol", signals.daily_price_vol),
        ("eligibility", signals.eligibility), ("liquidity", signals.liquidity),
        ("selections", signals.selections), ("directions", signals.directions),
        ("historical_fee_rules", fee_rules),
    ]:
        write_frame(frame, run_root / name)
    fee_rules.to_csv(run_root / "historical_fee_rules.csv", index=False, encoding="utf-8-sig")
    write_json(signals.diagnostics, run_root / "signal_diagnostics.json")
    for filename in ["fee_rule_coverage.csv", "tushare_fee_coverage.csv"]:
        source = project / "data" / "v3" / "fees" / filename
        if source.exists():
            shutil.copy2(source, run_root / filename)


def _write_both(frame: pd.DataFrame, base: Path) -> None:
    write_frame(frame, base)
    frame.to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8-sig")


def break_even_table(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stage, parameter, label in [
        ("06_break_even_tick", "固定滑点_tick", "固定基础滑点tick"),
        ("07_break_even_fee", "手续费倍数", "客户手续费倍数"),
    ]:
        subset = metrics[metrics["实验阶段"].eq(stage)].sort_values(parameter)
        for target, column in [
            ("全样本净利润降至0", "全样本净利润_元"),
            ("验证期Sharpe降至0", "验证期夏普比率"),
        ]:
            lower, upper, estimate = _zero_crossing(subset, parameter, column)
            rows.append({
                "成本轴": label, "目标": target, "插值估计": estimate,
                "相邻低参数": lower[parameter] if lower is not None else np.nan,
                "相邻低实际值": lower[column] if lower is not None else np.nan,
                "相邻高参数": upper[parameter] if upper is not None else np.nan,
                "相邻高实际值": upper[column] if upper is not None else np.nan,
                "是否在实测范围内穿越": lower is not None and upper is not None,
            })
    return pd.DataFrame(rows)


def _zero_crossing(
    frame: pd.DataFrame, parameter: str, value: str
) -> tuple[pd.Series | None, pd.Series | None, float]:
    previous = None
    for _, row in frame.iterrows():
        if previous is not None and float(previous[value]) > 0 >= float(row[value]):
            x1, x2 = float(previous[parameter]), float(row[parameter])
            y1, y2 = float(previous[value]), float(row[value])
            estimate = x1 + (0.0 - y1) * (x2 - x1) / (y2 - y1)
            return previous, row, estimate
        previous = row
    return None, None, np.nan


def _buffer_rebalance_stats(results: list[BacktestResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        scenario = result.scenario
        rows.append({
            "场景": scenario.name, "调仓模式": scenario.rebalance_mode,
            "buffer比例": scenario.buffer_fraction, "紧急阈值": scenario.emergency_vol_ratio,
            "正常调仓日": result.diagnostics.get("normal_rebalance_days", 0),
            "非正常调仓日": result.diagnostics.get("non_rebalance_days", 0),
            "buffer评估次数": result.diagnostics.get("buffer_evaluations", 0),
            "buffer阻止次数": result.diagnostics.get("buffer_holds", 0),
            "buffer阻止比例": result.diagnostics.get("buffer_holds", 0) / max(result.diagnostics.get("buffer_evaluations", 0), 1),
            "紧急波动率触发日": result.diagnostics.get("emergency_vol_trigger_days", 0),
            "紧急减仓日": result.diagnostics.get("emergency_vol_reduction_days", 0),
            "保证金强制缩减日": result.diagnostics.get("forced_constraint_days", 0),
            "订单数": len(result.orders), "成交分段数": len(result.fills),
        })
    return pd.DataFrame(rows)


def _v2_comparison(project: Path, v3_metrics: pd.DataFrame) -> pd.DataFrame:
    v2 = pd.read_csv(project / "outputs" / "v2_20260901_213543" / "scenario_summary.csv")
    v2_row = v2[
        v2["vol_target"].eq(0.275)
        & v2["unfilled_mode"].eq("cancel_recalculate")
        & v2["slippage_ticks"].eq(2.0)
    ].iloc[0]
    v3_row = v3_metrics[v3_metrics["标签"].eq("formal_baseline")].iloc[0]
    return pd.DataFrame([
        {"版本": "v2固定保守基准", "年化收益率": v2_row["full_annual_return"],
         "年化波动率": v2_row["full_annual_volatility"], "夏普比率": v2_row["full_sharpe"],
         "最大回撤": v2_row["full_max_drawdown"], "手续费_元": v2_row["full_total_fees"],
         "滑点成本_元": v2_row["full_total_slippage_cost"], "年化名义换手_倍": v2_row["full_annual_turnover"]},
        {"版本": "v3预注册正式基准", "年化收益率": v3_row["全样本年化收益率"],
         "年化波动率": v3_row["全样本年化波动率"], "夏普比率": v3_row["全样本夏普比率"],
         "最大回撤": v3_row["全样本最大回撤"], "手续费_元": v3_row["手续费_元"],
         "滑点成本_元": v3_row["滑点成本_元"], "年化名义换手_倍": v3_row["年化名义换手_倍"]},
    ])


def _fee_data_summary(project: Path) -> pd.DataFrame:
    direct = pd.read_csv(project / "data" / "v3" / "fees" / "tushare_fee_coverage.csv")
    interval = pd.read_csv(project / "data" / "v3" / "fees" / "fee_rule_coverage.csv")
    result = direct.rename(columns={
        "instrument_mapping": "instrument", "tushare_fee_days": "Tushare直接日数",
        "coverage_ratio": "Tushare直接覆盖率",
    })[["instrument", "mapping_days", "Tushare直接日数", "Tushare直接覆盖率"]]
    result = result.merge(interval[["instrument", "exact_tushare_days", "proxy_days", "exact_coverage_ratio"]], on="instrument")
    return result.rename(columns={
        "mapping_days": "主力映射日数", "exact_tushare_days": "Tushare规则区间覆盖日数",
        "proxy_days": "品种最新标准代理日数", "exact_coverage_ratio": "Tushare规则区间覆盖率",
    })


def _project_path(project: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project / path
