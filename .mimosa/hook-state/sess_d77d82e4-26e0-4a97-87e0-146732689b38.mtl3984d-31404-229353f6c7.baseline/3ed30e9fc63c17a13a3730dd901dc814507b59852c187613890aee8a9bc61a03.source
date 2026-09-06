from __future__ import annotations

import itertools
from pathlib import Path

import pandas as pd

from .analytics import scenario_summary, selection_summary, sector_contribution, yearly_performance
from .data_pipeline import load_bundle, normalize_and_build
from .engine import BacktestEngine, BacktestScenario
from .reports import write_engine_report, write_result_report
from .settings import Settings
from .signals import build_signals
from .storage import write_frame, write_json


def run_research(settings: Settings, rebuild_data: bool = False) -> Path:
    data = normalize_and_build(settings) if rebuild_data else load_bundle(settings)
    signals = build_signals(settings, data)
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    version = str(settings.raw.get("version", "v1"))
    run_root = settings.path.parent.parent / "outputs" / f"{version}_{timestamp}"
    run_root.mkdir(parents=True, exist_ok=True)
    write_frame(signals.scores, run_root / "scores")
    write_frame(signals.daily_price_vol, run_root / "daily_price_vol")
    write_frame(signals.eligibility, run_root / "eligibility")
    write_frame(signals.liquidity, run_root / "liquidity")
    write_frame(signals.selections, run_root / "selections")
    selection_summary(signals.selections).to_csv(
        run_root / "selection_summary.csv", index=False, encoding="utf-8-sig"
    )
    write_frame(signals.directions, run_root / "directions")
    write_json(signals.diagnostics, run_root / "signal_diagnostics.json")
    write_engine_report(settings, run_root / f"BACKTEST_ENGINE_AUDIT_{version}.md", data)

    scenarios = [
        BacktestScenario(float(vol), mode, float(slippage))
        for vol, mode, slippage in itertools.product(
            settings.section("portfolio")["annual_vol_targets"],
            settings.section("execution")["unfilled_modes"],
            settings.section("execution")["slippage_ticks"],
        )
    ]
    engine = BacktestEngine(settings, data, signals)
    results = []
    for scenario in scenarios:
        result = engine.run(scenario)
        results.append(result)
        scenario_root = run_root / scenario.name
        write_frame(result.equity, scenario_root / "daily_equity")
        write_frame(result.positions, scenario_root / "positions")
        write_frame(result.targets, scenario_root / "targets")
        write_frame(result.orders, scenario_root / "orders")
        write_frame(result.fills, scenario_root / "fills")
        write_frame(result.rejections, scenario_root / "rejections")
        write_frame(result.pnl_by_instrument, scenario_root / "pnl_by_instrument")
        write_json(result.diagnostics, scenario_root / "diagnostics.json")
    summary = scenario_summary(
        results, float(settings.section("run")["initial_capital"]),
        settings.section("run")["sample_split"],
    )
    write_frame(summary, run_root / "scenario_summary")
    summary.to_csv(run_root / "scenario_summary.csv", index=False, encoding="utf-8-sig")
    rejection_parts = []
    diagnostic_parts = []
    for result in results:
        if not result.rejections.empty:
            counts = result.rejections.groupby("reason").size().rename("count").reset_index()
            counts.insert(0, "scenario", result.scenario.name)
            rejection_parts.append(counts)
        diagnostic_parts.append({**result.diagnostics})
    rejection_summary = (
        pd.concat(rejection_parts, ignore_index=True)
        if rejection_parts else pd.DataFrame(columns=["scenario", "reason", "count"])
    )
    rejection_summary.to_csv(
        run_root / "rejection_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(diagnostic_parts).to_csv(
        run_root / "scenario_diagnostics.csv", index=False, encoding="utf-8-sig"
    )
    reference = next(
        result for result in results
        if result.scenario.annual_vol_target == float(settings.section("portfolio")["default_annual_vol_target"])
        and result.scenario.unfilled_mode == "cancel_recalculate"
        and result.scenario.slippage_ticks == max(settings.section("execution")["slippage_ticks"])
    )
    yearly_performance(reference, float(settings.section("run")["initial_capital"])).to_csv(
        run_root / "yearly_performance_reference.csv", index=False, encoding="utf-8-sig"
    )
    sector_contribution(
        reference, float(settings.section("run")["initial_capital"]),
        settings.section("run")["sample_split"],
    ).to_csv(run_root / "sector_contribution_reference.csv", index=False, encoding="utf-8-sig")
    write_result_report(
        settings, data, signals, summary, run_root / f"BACKTEST_RESULT_REPORT_{version}.md"
    )
    write_json(
        {"run_id": timestamp, "version": version, "config": str(settings.path), "scenarios": len(scenarios),
         "output": str(run_root)},
        run_root / "manifest.json",
    )
    return run_root
