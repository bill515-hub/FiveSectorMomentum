from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable

import numpy as np
import pandas as pd

from .analytics_v3 import cost_attribution
from .analytics_v4 import (
    concentration_v4, effective_weights_v4, forecast_correlations_v4,
    forecast_distribution_v4, marginal_pnl_v4, pnl_contribution_v4,
    robustness_v4, rolling_walk_forward_v4, scaling_statistics_v4,
    scenario_metrics_v4, yearly_performance_v4,
)
from .costs_v3 import FeeSchedule
from .data_pipeline import load_bundle
from .engine import BacktestResult
from .engine_v4 import BacktestEngineV4, V4Scenario
from .settings import Settings
from .signals_v4 import (
    ForecastLibraryV4, aggregate_from_library, build_forecast_library_v4,
    signal_bundle_from_forecast,
)
from .storage import read_frame, write_json


def registered_v4_scenarios(settings: Settings) -> list[V4Scenario]:
    config = settings.section("v4_research")
    horizons = tuple(int(item) for item in config["single_horizons"])
    scenarios: list[V4Scenario] = [
        V4Scenario("reference_v3_252", "00_reference", "reference", (252,), candidate=False)
    ]
    scenarios.extend(
        V4Scenario(f"single_{h}", "01_single_normal", "single_normal", (h,),
                   effective_window_days=h)
        for h in horizons
    )
    scenarios.extend(
        V4Scenario(f"single_{h}_skip5", "02_single_skip", "single_skip", (h,),
                   skip_recent_days=5, effective_window_days=h)
        for h in horizons
    )
    scenarios.append(V4Scenario(
        "single_250_minus_20", "02_single_skip", "single_skip", (250,),
        skip_recent_days=20, effective_window_days=230,
    ))
    combinations = {
        str(name): tuple(int(item) for item in values)
        for name, values in config["combinations"].items()
    }
    for aggregation in ("raw", "scaled"):
        for combo, combo_horizons in combinations.items():
            label = f"multi_{combo}_{aggregation}"
            scenarios.append(V4Scenario(
                label, "03_multi", f"multi_{aggregation}", combo_horizons,
                aggregation=aggregation,
            ))
    for aggregation in ("raw", "scaled"):
        for combo, combo_horizons in combinations.items():
            parent = f"multi_{combo}_{aggregation}"
            for omitted in combo_horizons:
                remaining = tuple(h for h in combo_horizons if h != omitted)
                scenarios.append(V4Scenario(
                    f"loo_{combo}_{aggregation}_without_{omitted}", "04_marginal_loo",
                    "marginal_diagnostic", remaining, aggregation=aggregation,
                    candidate=False, parent_label=parent, omitted_horizon=omitted,
                ))
    return scenarios


def forecast_for_scenario(library: ForecastLibraryV4, scenario: V4Scenario) -> pd.DataFrame:
    if scenario.family == "reference":
        return library.raw_reference_252
    if scenario.label == "single_250_minus_20":
        return library.raw_250_minus_20
    if scenario.family == "single_normal":
        return library.raw_regular[scenario.horizons[0]]
    if scenario.family == "single_skip":
        return library.raw_skip5[scenario.horizons[0]]
    if scenario.aggregation in {"raw", "scaled"}:
        return aggregate_from_library(library, scenario.horizons, scenario.aggregation == "scaled")
    raise KeyError(f"No forecast rule for {scenario}")


def run_v4_research(settings: Settings) -> Path:
    if settings.raw.get("version") != "v4":
        raise ValueError("run_v4_research requires a v4 config")
    project = settings.path.parent.parent
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    run_root = project / "outputs" / f"v4_{timestamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(settings.path, run_root / "five_sector_momentum_v4.yaml")
    shutil.copy2(project / "V4_EXPERIMENT_REGISTRY.md", run_root / "V4_EXPERIMENT_REGISTRY.md")
    _run_test_suite(project, run_root)

    data = load_bundle(settings)
    library = build_forecast_library_v4(settings, data)
    fee_path = _project_path(project, settings.section("fees")["rules_path"])
    fee_schedule = FeeSchedule.load(fee_path)
    scenarios = registered_v4_scenarios(settings)
    _write_both(pd.DataFrame([_scenario_row(item) for item in scenarios]), run_root / "scenario_registry_v4")
    _save_forecast_library(run_root, library, settings)
    _save_inherited_inputs(project, run_root, library, data)

    results: list[BacktestResult] = []
    signal_cache: dict[str, object] = {}
    result_by_label: dict[str, BacktestResult] = {}

    # Hard gate: reproduce frozen v3 before looking at any candidate result.
    reference = scenarios[0]
    reference_result = _run_scenario(
        settings, data, library, fee_schedule, reference, run_root, signal_cache
    )
    results.append(reference_result)
    result_by_label[reference.label] = reference_result
    reproduction = _reproduction_gate(project, reference_result)
    _write_both(reproduction, run_root / "v3_reproduction_gate_v4")
    if not bool(reproduction["是否通过"].all()):
        write_json({
            "version": "v4", "run_id": timestamp, "status": "reproduction_gate_failed",
            "candidate_scenarios_run": 0, "v2_v3_modified": False,
        }, run_root / "manifest.json")
        raise RuntimeError(f"v3 reproduction gate failed; see {run_root}")

    # Fixed registry order: all candidates, then LOO diagnostics.
    for scenario in scenarios[1:]:
        result = _run_scenario(
            settings, data, library, fee_schedule, scenario, run_root, signal_cache
        )
        results.append(result)
        result_by_label[scenario.label] = result

    initial = float(settings.section("run")["initial_capital"])
    split = str(settings.section("run")["sample_split"])
    end = str(settings.section("run")["end"])
    tables = _build_result_tables(results, scenarios, initial, split, end, data.instrument_meta)
    for name, frame in tables.items():
        _write_both(frame, run_root / name)

    selection = _select_pressure_candidates(
        tables["scenario_metrics_v4"], tables["robustness_v4"],
        tables["concentration_v4"], scenarios,
        float(settings.section("v4_research")["replacement_cost_turnover_cap_ratio"]),
        int(settings.section("v4_research")["maximum_pressure_candidates"]),
    )
    _write_both(selection, run_root / "candidate_selection_v4")
    _write_both(
        _skip_recent_impact(tables["scenario_metrics_v4"], tables["concentration_v4"]),
        run_root / "skip_recent_impact_v4",
    )

    pressure_scenarios: list[V4Scenario] = []
    for label in selection.loc[selection["进入滑点压力复核"], "标签"]:
        parent = next(item for item in scenarios if item.label == label)
        for ticks in settings.section("v4_research")["pressure_fixed_ticks"]:
            pressure = replace(
                parent, label=f"{parent.label}_fixed_{int(ticks)}tick",
                stage="05_pressure", family="pressure", candidate=False,
                parent_label=parent.label, slippage_model="fixed",
                fixed_slippage_ticks=float(ticks),
            )
            result = _run_scenario(
                settings, data, library, fee_schedule, pressure, run_root, signal_cache,
                forecast_parent=parent,
            )
            pressure_scenarios.append(pressure)
            results.append(result)
            result_by_label[pressure.label] = result

    if pressure_scenarios:
        pressure_tables = _build_result_tables(
            results, scenarios + pressure_scenarios, initial, split, end, data.instrument_meta
        )
        # Replace aggregate tables with their final all-scenario versions.
        for name, frame in pressure_tables.items():
            _write_both(frame, run_root / name)
        tables = pressure_tables
    pressure_metrics = tables["scenario_metrics_v4"][
        tables["scenario_metrics_v4"]["实验阶段"].eq("05_pressure")
    ].copy()
    _write_both(pressure_metrics, run_root / "slippage_pressure_v4")

    recommendation = _recommendation_table(
        tables["scenario_metrics_v4"], tables["robustness_v4"],
        tables["concentration_v4"], selection, scenarios,
    )
    _write_both(recommendation, run_root / "final_recommendation_v4")
    comparison = _v3_v4_comparison(
        tables["scenario_metrics_v4"], tables["concentration_v4"], recommendation,
        scenarios,
    )
    _write_both(comparison, run_root / "v3_v4_comparison")

    reconciliation, execution_stats = _accounting_audit_all(
        results, scenarios + pressure_scenarios, tables["pnl_contribution_v4"],
        initial,
    )
    _write_both(reconciliation, run_root / "accounting_reconciliation_v4")
    _write_both(execution_stats, run_root / "execution_audit_statistics_v4")
    traceability = _traceability(run_root)
    _write_both(traceability, run_root / "pickle_csv_traceability_v4")

    write_json({
        "version": "v4", "run_id": timestamp, "status": "complete",
        "config": str(settings.path), "output": str(run_root),
        "v3_reproduction_passed": True,
        "base_scenario_count": len(scenarios),
        "candidate_count": int(sum(item.candidate for item in scenarios)),
        "pressure_scenario_count": len(pressure_scenarios),
        "all_scenario_count": len(results),
        "recommended_label": recommendation.iloc[0]["推荐标签"],
        "retain_v3": bool(recommendation.iloc[0]["是否保留v3"]),
        "v2_v3_modified": False,
    }, run_root / "manifest.json")

    from .reports_v4 import write_engine_audit_v4, write_result_report_v4
    write_engine_audit_v4(settings, data, run_root)
    write_result_report_v4(settings, run_root)
    return run_root


def _run_scenario(
    settings: Settings, data, library: ForecastLibraryV4, fee_schedule: FeeSchedule,
    scenario: V4Scenario, run_root: Path, signal_cache: dict[str, object],
    forecast_parent: V4Scenario | None = None,
) -> BacktestResult:
    signal_key = forecast_parent.label if forecast_parent is not None else scenario.label
    if signal_key not in signal_cache:
        source_scenario = forecast_parent or scenario
        forecast = forecast_for_scenario(library, source_scenario)
        signal_cache[signal_key] = signal_bundle_from_forecast(
            settings, data, library, forecast, source_scenario.label,
            diagnostics_extra={
                "horizons": list(source_scenario.horizons),
                "aggregation": source_scenario.aggregation,
                "skip_recent_days": source_scenario.skip_recent_days,
                "effective_window_days": source_scenario.effective_window_days,
            },
        )
    signals = signal_cache[signal_key]
    result = BacktestEngineV4(settings, data, signals, fee_schedule).run_v4(scenario)
    root = run_root / scenario.name
    for name, frame in [
        ("daily_equity", result.equity), ("positions", result.positions),
        ("targets", result.targets), ("orders", result.orders), ("fills", result.fills),
        ("rejections", result.rejections), ("pnl_by_instrument", result.pnl_by_instrument),
        ("scores", signals.scores), ("selections", signals.selections),
        ("directions", signals.directions),
    ]:
        _write_both(frame, root / name)
    write_json(result.diagnostics, root / "diagnostics.json")
    write_json(_scenario_row(scenario), root / "scenario_parameters.json")
    print(f"completed {scenario.name}", flush=True)
    return result


def _build_result_tables(
    results: list[BacktestResult], scenarios: list[V4Scenario], initial: float,
    split: str, end: str, instrument_meta: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    metrics = scenario_metrics_v4(results, scenarios, initial, split)
    yearly = pd.concat([
        yearly_performance_v4(result, result.scenario.name, initial, end)
        for result in results
    ], ignore_index=True)
    rolling = pd.concat([
        rolling_walk_forward_v4(result, result.scenario.name, initial)
        for result in results
    ], ignore_index=True)
    robust = pd.concat([
        robustness_v4(result, result.scenario.name, initial, split)
        for result in results
    ], ignore_index=True)
    contribution_frames = [
        pnl_contribution_v4(result, result.scenario.name, split) for result in results
    ]
    contributions = pd.concat(contribution_frames, ignore_index=True)
    concentrations = pd.concat([
        concentration_v4(result, result.scenario.name, contribution)
        for result, contribution in zip(results, contribution_frames)
    ], ignore_index=True)
    costs = pd.concat([
        cost_attribution(result, instrument_meta).assign(场景=result.scenario.name)
        for result in results
    ], ignore_index=True)
    rebalance = pd.DataFrame([{
        "场景": result.scenario.name,
        "正常调仓日": result.diagnostics.get("normal_rebalance_days", 0),
        "非正常调仓日": result.diagnostics.get("non_rebalance_days", 0),
        "buffer评估次数": result.diagnostics.get("buffer_evaluations", 0),
        "buffer阻止次数": result.diagnostics.get("buffer_holds", 0),
        "buffer实际交易次数": result.diagnostics.get("buffer_trades", 0),
        "buffer阻止比例": result.diagnostics.get("buffer_holds", 0) / max(result.diagnostics.get("buffer_evaluations", 0), 1),
        "紧急波动率触发日": result.diagnostics.get("emergency_vol_trigger_days", 0),
        "紧急减仓日": result.diagnostics.get("emergency_vol_reduction_days", 0),
        "保证金强制缩减日": result.diagnostics.get("forced_constraint_days", 0),
        "订单数": len(result.orders), "成交分段数": len(result.fills),
    } for result in results])
    margin = pd.DataFrame([{
        "场景": result.scenario.name,
        "平均总保证金占用": result.equity["margin_utilization"].mean(),
        "峰值总保证金占用": result.equity["margin_utilization"].max(),
        "平均商品保证金占用": result.equity["commodity_margin_utilization"].mean(),
        "峰值商品保证金占用": result.equity["commodity_margin_utilization"].max(),
        "平均商品名义杠杆": result.equity["commodity_gross_leverage"].mean(),
        "峰值商品名义杠杆": result.equity["commodity_gross_leverage"].max(),
        "平均国债名义杠杆": result.equity["exempt_gross_leverage"].mean(),
        "峰值国债名义杠杆": result.equity["exempt_gross_leverage"].max(),
    } for result in results])
    return {
        "scenario_parameters_v4": pd.DataFrame([_scenario_row(item) for item in scenarios]),
        "scenario_metrics_v4": metrics,
        "yearly_performance_v4": yearly,
        "rolling_walk_forward_v4": rolling,
        "robustness_v4": robust,
        "pnl_contribution_v4": contributions,
        "concentration_v4": concentrations,
        "cost_attribution_v4": costs,
        "rebalance_buffer_statistics_v4": rebalance,
        "margin_leverage_v4": margin,
        "marginal_pnl_v4": marginal_pnl_v4(metrics),
    }


def _save_forecast_library(run_root: Path, library: ForecastLibraryV4, settings: Settings) -> None:
    for horizon, frame in library.raw_regular.items():
        _write_both(_wide(frame, "forecast"), run_root / "forecasts" / f"raw_{horizon}")
    for horizon, frame in library.raw_skip5.items():
        _write_both(_wide(frame, "forecast"), run_root / "forecasts" / f"skip5_{horizon}")
    for horizon, frame in library.scaled_regular.items():
        _write_both(_wide(frame, "forecast"), run_root / "forecasts" / f"scaled_{horizon}")
    _write_both(_wide(library.raw_reference_252, "forecast"), run_root / "forecasts" / "reference_252")
    _write_both(_wide(library.raw_250_minus_20, "forecast"), run_root / "forecasts" / "250_minus_20")
    scalars = pd.concat(library.scalars, axis=1).rename_axis(index="date", columns="horizon").reset_index()
    _write_both(scalars, run_root / "forecast_scalars_v4")
    split = str(settings.section("run")["sample_split"])
    combinations = settings.section("v4_research")["combinations"]
    multi_distribution_rows = []
    split_date = pd.Timestamp(split)
    for combo, horizons in combinations.items():
        for version in ("raw", "scaled"):
            aggregate = aggregate_from_library(library, tuple(horizons), version == "scaled")
            for phase, subset in {
                "全样本": aggregate,
                "样本内": aggregate[aggregate.index < split_date],
                "验证期": aggregate[aggregate.index >= split_date],
            }.items():
                values = subset.stack().dropna()
                multi_distribution_rows.append({
                    "组合": combo, "版本": version, "阶段": phase,
                    "周期": ",".join(map(str, horizons)), "有效forecast数": len(values),
                    "缺失比例": float(subset.isna().mean().mean()),
                    "均值": values.mean() if len(values) else np.nan,
                    "平均绝对值": values.abs().mean() if len(values) else np.nan,
                    "标准差": values.std(ddof=1) if len(values) > 1 else np.nan,
                    "P05": values.quantile(.05) if len(values) else np.nan,
                    "P50": values.quantile(.50) if len(values) else np.nan,
                    "P95": values.quantile(.95) if len(values) else np.nan,
                })
    _write_both(pd.DataFrame(multi_distribution_rows), run_root / "multi_forecast_distribution_v4")
    for name, frame in [
        ("forecast_distribution_v4", forecast_distribution_v4(library, split)),
        ("forecast_scaling_statistics_v4", scaling_statistics_v4(library, split)),
        ("forecast_correlations_v4", forecast_correlations_v4(library, split)),
        ("forecast_effective_weights_v4", effective_weights_v4(library, combinations, split)),
    ]:
        _write_both(frame, run_root / name)


def _save_inherited_inputs(
    project: Path, run_root: Path, library: ForecastLibraryV4, data,
) -> None:
    for name, frame in [
        ("daily_price_vol_v4", _wide(library.daily_vol, "daily_price_vol")),
        ("eligibility_v4", _wide(library.eligibility, "eligible")),
        ("median_volume_v4", _wide(library.median_volume, "median_volume")),
        ("median_open_interest_v4", _wide(library.median_open_interest, "median_open_interest")),
    ]:
        _write_both(frame, run_root / name)
    write_json(data.diagnostics, run_root / "data_diagnostics_v4.json")
    sources = [
        project / "data" / "v3" / "fees" / "historical_fee_rules.pkl",
        project / "data" / "v3" / "fees" / "historical_fee_rules.csv",
        project / "data" / "v3" / "fees" / "fee_rule_coverage.csv",
        project / "data" / "v3" / "fees" / "tushare_fee_coverage.csv",
        project / "outputs" / "v3_20260902_001129" / "official_source_inventory_v3.csv",
    ]
    for source in sources:
        if source.exists():
            shutil.copy2(source, run_root / source.name)


def _run_test_suite(project: Path, run_root: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = f"{project / 'src'}{os.pathsep}{project / 'tests'}"
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        cwd=project, env=environment, text=True, capture_output=True,
    )
    text = completed.stdout + completed.stderr
    (run_root / "test_results_v4.txt").write_text(text, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"v4 tests failed; see {run_root / 'test_results_v4.txt'}")


def _reproduction_gate(project: Path, reference: BacktestResult) -> pd.DataFrame:
    old_root = project / "outputs" / "v3_20260902_001129" / "00_formal__formal_baseline"
    rows = []
    comparisons = {
        "权益记录": (reference.equity, read_frame(old_root / "daily_equity"), ["date"]),
        "持仓记录": (reference.positions, read_frame(old_root / "positions"), ["date", "contract", "instrument"]),
        "目标记录": (reference.targets, read_frame(old_root / "targets"), ["date", "contract", "instrument"]),
        "订单记录": (reference.orders, read_frame(old_root / "orders"), ["created_date", "contract", "instrument", "quantity", "reason"]),
        "成交记录": (reference.fills, read_frame(old_root / "fills"), ["date", "created_date", "contract", "instrument", "attempt", "transaction_type"]),
        "逐品种盈亏": (reference.pnl_by_instrument, read_frame(old_root / "pnl_by_instrument"), ["date", "contract", "instrument"]),
    }
    for label, (new, old, keys) in comparisons.items():
        common = [column for column in new.columns if column in old.columns and column != "scenario"]
        usable_keys = [key for key in keys if key in common]
        new_cmp = new[common].sort_values(usable_keys, kind="stable").reset_index(drop=True)
        old_cmp = old[common].sort_values(usable_keys, kind="stable").reset_index(drop=True)
        rows_equal = len(new_cmp) == len(old_cmp)
        max_numeric = np.inf
        exact_non_numeric = False
        if rows_equal:
            numeric = [
                column for column in common
                if pd.api.types.is_numeric_dtype(new_cmp[column])
                and not pd.api.types.is_bool_dtype(new_cmp[column])
            ]
            non_numeric = [column for column in common if column not in numeric]
            max_numeric = max(
                [float((new_cmp[column] - old_cmp[column]).abs().max()) for column in numeric]
                + [0.0]
            )
            exact_non_numeric = all(new_cmp[column].equals(old_cmp[column]) for column in non_numeric)
        passed = rows_equal and max_numeric <= 0.01 and exact_non_numeric
        rows.append({
            "检查项": label, "v4行数": len(new_cmp), "v3行数": len(old_cmp),
            "最大数值绝对差": max_numeric, "非数值列完全一致": exact_non_numeric,
            "比较口径": "按业务主键固定排序后逐行比较",
            "容差_元或数值": 0.01, "是否通过": passed,
        })
    rows.extend([
        {"检查项": "期末权益", "v4行数": 1, "v3行数": 1,
         "最大数值绝对差": abs(reference.equity["equity"].iloc[-1] - read_frame(old_root / "daily_equity")["equity"].iloc[-1]),
         "非数值列完全一致": True, "比较口径": "汇总值", "容差_元或数值": 0.01,
         "是否通过": abs(reference.equity["equity"].iloc[-1] - read_frame(old_root / "daily_equity")["equity"].iloc[-1]) <= .01},
        {"检查项": "总客户手续费", "v4行数": 1, "v3行数": 1,
         "最大数值绝对差": abs(reference.fills["commission"].sum() - read_frame(old_root / "fills")["commission"].sum()),
         "非数值列完全一致": True, "比较口径": "汇总值", "容差_元或数值": 0.01,
         "是否通过": abs(reference.fills["commission"].sum() - read_frame(old_root / "fills")["commission"].sum()) <= .01},
        {"检查项": "总滑点成本", "v4行数": 1, "v3行数": 1,
         "最大数值绝对差": abs(reference.fills["slippage_cost"].sum() - read_frame(old_root / "fills")["slippage_cost"].sum()),
         "非数值列完全一致": True, "比较口径": "汇总值", "容差_元或数值": 0.01,
         "是否通过": abs(reference.fills["slippage_cost"].sum() - read_frame(old_root / "fills")["slippage_cost"].sum()) <= .01},
    ])
    return pd.DataFrame(rows)


def _select_pressure_candidates(
    metrics: pd.DataFrame, robustness: pd.DataFrame, concentration: pd.DataFrame,
    scenarios: list[V4Scenario], cost_cap: float, maximum: int,
) -> pd.DataFrame:
    reference_name = next(item.name for item in scenarios if item.family == "reference")
    ref = metrics[metrics["场景"].eq(reference_name)].iloc[0]
    ref_conc = concentration[concentration["场景"].eq(reference_name)].iloc[0]
    robust_slice = robustness[
        robustness["切片"].eq("同时删除2020和2024年")
        & robustness["阶段"].eq("全样本") & robustness["成本口径"].eq("含成本")
    ].set_index("场景")
    candidate_names = [item.name for item in scenarios if item.candidate]
    rows = []
    for _, metric in metrics[metrics["场景"].isin(candidate_names)].iterrows():
        conc = concentration[concentration["场景"].eq(metric["场景"])].iloc[0]
        deleted = robust_slice.loc[metric["场景"]]
        gates = {
            "样本内验证期均正": metric["样本内年化收益率"] > 0 and metric["验证期年化收益率"] > 0,
            "滚动拼接为正": metric["滚动下一年拼接年化收益率"] > 0,
            "删除关键年仍正": deleted["年化收益率"] > 0 and deleted["夏普比率"] > 0,
            "回撤或Calmar改善": metric["全样本最大回撤"] >= ref["全样本最大回撤"] or metric["全样本Calmar比率"] >= 1.05 * ref["全样本Calmar比率"],
            "成本换手不过度": metric["总交易成本_元"] <= cost_cap * ref["总交易成本_元"] and metric["年化名义换手_倍"] <= cost_cap * ref["年化名义换手_倍"],
            "年份集中不恶化": conc["正盈利年份前两名占比"] <= ref_conc["正盈利年份前两名占比"],
            "FG和板块集中不恶化": _nan_le(conc["FG占化工正利润比"], ref_conc["FG占化工正利润比"]) and conc["单一板块正利润占比"] <= ref_conc["单一板块正利润占比"],
        }
        rows.append({
            "场景": metric["场景"], "标签": metric["标签"], "家族": metric["家族"],
            **gates, "通过门槛数": sum(gates.values()),
            "核心三门是否通过": all(list(gates.values())[:3]),
            "验证期夏普": metric["验证期夏普比率"],
            "删除2020和2024夏普": deleted["夏普比率"],
            "Calmar": metric["全样本Calmar比率"],
            "年份前二占比": conc["正盈利年份前两名占比"],
            "FG占化工正利润比": conc["FG占化工正利润比"],
            "年化换手": metric["年化名义换手_倍"],
        })
    selection = pd.DataFrame(rows).sort_values(
        ["通过门槛数", "验证期夏普", "删除2020和2024夏普", "Calmar", "年份前二占比", "年化换手"],
        ascending=[False, False, False, False, True, True],
    ).reset_index(drop=True)
    eligible = selection[selection["核心三门是否通过"]]
    chosen: list[str] = []
    family_groups = {
        "单周期": ["single_normal", "single_skip"],
        "原始多周期": ["multi_raw"], "缩放多周期": ["multi_scaled"],
    }
    for families in family_groups.values():
        family = eligible[eligible["家族"].isin(families)]
        if not family.empty:
            chosen.append(str(family.iloc[0]["标签"]))
    if len(chosen) < maximum:
        for label in eligible["标签"]:
            if label not in chosen:
                chosen.append(str(label))
            if len(chosen) >= maximum:
                break
    selection["进入滑点压力复核"] = selection["标签"].isin(chosen[:maximum])
    selection["预注册排序"] = np.arange(1, len(selection) + 1)
    return selection


def _skip_recent_impact(metrics: pd.DataFrame, concentration: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in (20, 60, 120, 180, 250):
        base = metrics[metrics["标签"].eq(f"single_{horizon}")].iloc[0]
        skipped = metrics[metrics["标签"].eq(f"single_{horizon}_skip5")].iloc[0]
        base_conc = concentration[concentration["场景"].eq(base["场景"])].iloc[0]
        skipped_conc = concentration[concentration["场景"].eq(skipped["场景"])].iloc[0]
        rows.append({
            "周期": horizon, "比较": "跳过5日-普通",
            "全样本年化收益变化": skipped["全样本年化收益率"] - base["全样本年化收益率"],
            "验证期年化收益变化": skipped["验证期年化收益率"] - base["验证期年化收益率"],
            "最大回撤变化_正数为改善": skipped["全样本最大回撤"] - base["全样本最大回撤"],
            "年化换手变化": skipped["年化名义换手_倍"] - base["年化名义换手_倍"],
            "手续费变化_元": skipped["手续费_元"] - base["手续费_元"],
            "滑点变化_元": skipped["滑点成本_元"] - base["滑点成本_元"],
            "2020和2024利润占比变化": skipped_conc["2020和2024占累计净利润"] - base_conc["2020和2024占累计净利润"],
            "年份前二占比变化": skipped_conc["正盈利年份前两名占比"] - base_conc["正盈利年份前两名占比"],
        })
    base = metrics[metrics["标签"].eq("single_250")].iloc[0]
    skipped = metrics[metrics["标签"].eq("single_250_minus_20")].iloc[0]
    base_conc = concentration[concentration["场景"].eq(base["场景"])].iloc[0]
    skipped_conc = concentration[concentration["场景"].eq(skipped["场景"])].iloc[0]
    rows.append({
        "周期": 250, "比较": "跳过20日230点差-普通250日",
        "全样本年化收益变化": skipped["全样本年化收益率"] - base["全样本年化收益率"],
        "验证期年化收益变化": skipped["验证期年化收益率"] - base["验证期年化收益率"],
        "最大回撤变化_正数为改善": skipped["全样本最大回撤"] - base["全样本最大回撤"],
        "年化换手变化": skipped["年化名义换手_倍"] - base["年化名义换手_倍"],
        "手续费变化_元": skipped["手续费_元"] - base["手续费_元"],
        "滑点变化_元": skipped["滑点成本_元"] - base["滑点成本_元"],
        "2020和2024利润占比变化": skipped_conc["2020和2024占累计净利润"] - base_conc["2020和2024占累计净利润"],
        "年份前二占比变化": skipped_conc["正盈利年份前两名占比"] - base_conc["正盈利年份前两名占比"],
    })
    return pd.DataFrame(rows)


def _recommendation_table(
    metrics: pd.DataFrame, robustness: pd.DataFrame, concentration: pd.DataFrame,
    selection: pd.DataFrame, scenarios: list[V4Scenario],
) -> pd.DataFrame:
    reference_name = next(item.name for item in scenarios if item.family == "reference")
    ref = metrics[metrics["场景"].eq(reference_name)].iloc[0]
    ref_conc = concentration[concentration["场景"].eq(reference_name)].iloc[0]
    pressure = metrics[metrics["实验阶段"].eq("05_pressure")]
    robust_deleted = robustness[
        robustness["切片"].eq("同时删除2020和2024年")
        & robustness["阶段"].eq("全样本") & robustness["成本口径"].eq("含成本")
    ].set_index("场景")
    qualifying = []
    for _, row in selection[selection["进入滑点压力复核"]].iterrows():
        metric = metrics[metrics["标签"].eq(row["标签"])].iloc[0]
        conc = concentration[concentration["场景"].eq(metric["场景"])].iloc[0]
        pressure_rows = pressure[pressure["父组合"].eq(row["标签"])]
        pressure_ok = len(pressure_rows) == 2 and (pressure_rows["验证期年化收益率"] > 0).all()
        adjacent_ok = _neighbor_stability(row["标签"], metrics, scenarios)
        strict = (
            bool(row["核心三门是否通过"]) and pressure_ok and adjacent_ok
            and metric["全样本最大回撤"] >= ref["全样本最大回撤"]
            and conc["正盈利年份前两名占比"] < ref_conc["正盈利年份前两名占比"]
            and _nan_le(conc["FG占化工正利润比"], ref_conc["FG占化工正利润比"])
        )
        if strict:
            qualifying.append((row, metric, conc))
    if not qualifying:
        return pd.DataFrame([{
            "推荐标签": "reference_v3_252", "是否保留v3": True,
            "结论": "v4没有足够证据替换v3信号",
            "推荐全样本年化收益率": ref["全样本年化收益率"],
            "推荐验证期年化收益率": ref["验证期年化收益率"],
            "推荐最大回撤": ref["全样本最大回撤"],
            "推荐年份前二占比": ref_conc["正盈利年份前两名占比"],
            "推荐FG占化工正利润比": ref_conc["FG占化工正利润比"],
            "理由": "没有压力候选同时满足预注册的核心稳健性、邻近一致性、压力滑点、回撤和集中度替换门槛。",
        }])
    qualifying.sort(key=lambda item: (
        item[0]["通过门槛数"], item[0]["验证期夏普"],
        item[0]["删除2020和2024夏普"], item[0]["Calmar"],
    ), reverse=True)
    row, metric, conc = qualifying[0]
    return pd.DataFrame([{
        "推荐标签": row["标签"], "是否保留v3": False,
        "结论": f"采用固定v4方案 {row['标签']}",
        "推荐全样本年化收益率": metric["全样本年化收益率"],
        "推荐验证期年化收益率": metric["验证期年化收益率"],
        "推荐最大回撤": metric["全样本最大回撤"],
        "推荐年份前二占比": conc["正盈利年份前两名占比"],
        "推荐FG占化工正利润比": conc["FG占化工正利润比"],
        "理由": "通过预注册替换门槛与2/3 tick压力复核，并按预注册排序领先。",
    }])


def _v3_v4_comparison(
    metrics: pd.DataFrame, concentration: pd.DataFrame, recommendation: pd.DataFrame,
    scenarios: list[V4Scenario],
) -> pd.DataFrame:
    reference_name = next(item.name for item in scenarios if item.family == "reference")
    recommended_label = str(recommendation.iloc[0]["推荐标签"])
    recommended = metrics[metrics["标签"].eq(recommended_label)]
    if recommended.empty:
        recommended = metrics[metrics["场景"].eq(reference_name)]
    rows = []
    for version, metric in [
        ("v3正式基准（v4精确复现）", metrics[metrics["场景"].eq(reference_name)].iloc[0]),
        ("v4最终推荐", recommended.iloc[0]),
    ]:
        conc = concentration[concentration["场景"].eq(metric["场景"])].iloc[0]
        rows.append({
            "方案": version, "标签": metric["标签"],
            "全样本年化收益率": metric["全样本年化收益率"],
            "全样本夏普": metric["全样本夏普比率"],
            "验证期年化收益率": metric["验证期年化收益率"],
            "验证期夏普": metric["验证期夏普比率"],
            "最大回撤": metric["全样本最大回撤"],
            "年份前二正利润占比": conc["正盈利年份前两名占比"],
            "2020和2024占累计净利润": conc["2020和2024占累计净利润"],
            "FG占化工正利润比": conc["FG占化工正利润比"],
            "单一板块正利润占比": conc["单一板块正利润占比"],
            "年化换手": metric["年化名义换手_倍"],
            "总交易成本_元": metric["总交易成本_元"],
        })
    return pd.DataFrame(rows)


def _neighbor_stability(label: str, metrics: pd.DataFrame, scenarios: list[V4Scenario]) -> bool:
    scenario = next(item for item in scenarios if item.label == label)
    if scenario.family.startswith("single"):
        if label == "single_250_minus_20":
            neighbors = ["single_250", "single_250_skip5"]
        else:
            same = sorted(
                [item for item in scenarios if item.family == scenario.family and item.label != "single_250_minus_20"],
                key=lambda item: item.horizons[0],
            )
            index = [item.label for item in same].index(label)
            neighbors = [item.label for item in same[max(0, index-1):index] + same[index+1:index+2]]
    else:
        sibling_aggregation = "scaled" if scenario.aggregation == "raw" else "raw"
        sibling = next((
            item.label for item in scenarios
            if item.aggregation == sibling_aggregation and item.horizons == scenario.horizons
            and item.stage == "03_multi"
        ), None)
        neighbors = [sibling] if sibling else []
    if not neighbors:
        return False
    values = metrics[metrics["标签"].isin(neighbors)]["验证期年化收益率"]
    return len(values) == len(neighbors) and bool((values > 0).all())


def _accounting_audit_all(
    results: list[BacktestResult], scenarios: list[V4Scenario],
    contributions: pd.DataFrame, initial: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    checks = []
    stats = []
    for result in results:
        equity, fills, pnl = result.equity, result.fills, result.pnl_by_instrument
        previous = equity["equity"].shift(1).fillna(initial)
        full = contributions[(contributions["场景"].eq(result.scenario.name)) & contributions["阶段"].eq("全样本")]
        values = {
            "逐日权益增量=净盈亏": float((equity["equity"] - previous - equity["net_pnl"]).abs().max()),
            "累计净盈亏=期末权益差": float(abs(equity["net_pnl"].sum() - (equity["equity"].iloc[-1] - initial))),
            "毛盈亏-手续费=净盈亏": float(abs((equity["gross_pnl"] - equity["fees"] - equity["net_pnl"]).sum())),
            "成交手续费=账户手续费": float(abs(fills["commission"].sum() - equity["fees"].sum())),
            "逐品种净盈亏=账户净盈亏": float(abs(pnl["net_pnl"].sum() - equity["net_pnl"].sum())),
            "贡献表净利润=账户净盈亏": float(abs(full["净利润_元"].sum() - equity["net_pnl"].sum())),
            "客户手续费=交易所手续费x1.5": float(abs(fills["commission"].sum() - fills["exchange_commission"].sum() * 1.5)),
        }
        for check, error in values.items():
            checks.append({"场景": result.scenario.name, "检查项": check, "绝对误差": error, "容差": .01, "是否通过": error <= .01})
        stats.append({
            "场景": result.scenario.name, "成交分段数": len(fills),
            "开仓分段": int(fills["transaction_type"].eq("open").sum()),
            "非日内平仓分段": int(fills["transaction_type"].eq("close_non_today").sum()),
            "平今分段": int(fills["transaction_type"].eq("close_today").sum()),
            "代理费用分段": int(fills["fee_is_proxy"].astype(bool).sum()),
            "市场冲击分段": int(fills["impact_ticks"].gt(0).sum()),
            "最大参与率": float(fills["participation_rate"].max()),
            "费率规则缺失": int(fills["fee_rule_id"].isna().sum()),
            "来源链接缺失": int(fills["fee_source_url"].isna().sum()),
        })
    return pd.DataFrame(checks), pd.DataFrame(stats)


def _traceability(run_root: Path) -> pd.DataFrame:
    rows = []
    for pickle in sorted(run_root.rglob("*.pkl")):
        csv = pickle.with_suffix(".csv")
        try:
            frame = pd.read_pickle(pickle)
            rows.append({
                "pickle": str(pickle.relative_to(run_root)),
                "csv": str(csv.relative_to(run_root)) if csv.exists() else "",
                "行数": len(frame), "列数": len(frame.columns),
                "是否成对": csv.exists(),
            })
        except Exception:
            rows.append({"pickle": str(pickle.relative_to(run_root)), "csv": "", "行数": np.nan, "列数": np.nan, "是否成对": False})
    return pd.DataFrame(rows)


def _scenario_row(scenario: V4Scenario) -> dict[str, object]:
    row = asdict(scenario)
    row["name"] = scenario.name
    row["horizons"] = ",".join(map(str, scenario.horizons))
    execution = scenario.execution_scenario()
    row.update({
        "annual_vol_target": execution.annual_vol_target,
        "fee_multiplier": execution.fee_multiplier,
        "rebalance_mode": execution.rebalance_mode,
        "buffer_fraction": execution.buffer_fraction,
        "emergency_vol_ratio": execution.emergency_vol_ratio,
        "unfilled_mode": execution.unfilled_mode,
    })
    return row


def _wide(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    return frame.rename_axis(index="date", columns="instrument").stack(future_stack=True).rename(value_name).reset_index()


def _write_both(frame: pd.DataFrame, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    frame.to_pickle(base.with_suffix(".pkl"))
    frame.to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8-sig")


def _project_path(project: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project / path


def _nan_le(left: float, right: float) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    return bool(left <= right)
