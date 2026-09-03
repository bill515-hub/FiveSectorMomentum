from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.engine import BacktestResult
from five_sector_momentum.engine_v4 import V4Scenario
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4
from five_sector_momentum.workflow_v4 import (
    _accounting_audit_all, _build_result_tables, _recommendation_table,
    _save_forecast_library, _select_pressure_candidates, _skip_recent_impact,
    _traceability, _v3_v4_comparison, _write_both, registered_v4_scenarios,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="按已保存交易结果重建v4分析表和报告")
    parser.add_argument("run_root")
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    project = root.parents[1]
    settings = Settings.load(project / "configs" / "five_sector_momentum_v4.yaml")
    parameter_table = pd.read_pickle(root / "scenario_parameters_v4.pkl")
    scenarios = [_scenario_from_row(row) for _, row in parameter_table.iterrows()]
    results = [_load_result(root, scenario) for scenario in scenarios]
    initial = float(settings.section("run")["initial_capital"])
    split = str(settings.section("run")["sample_split"])
    end = str(settings.section("run")["end"])
    data = load_bundle(settings)
    tables = _build_result_tables(results, scenarios, initial, split, end, data.instrument_meta)
    for name, frame in tables.items():
        _write_both(frame, root / name)

    base_scenarios = registered_v4_scenarios(settings)
    selection = _select_pressure_candidates(
        tables["scenario_metrics_v4"], tables["robustness_v4"],
        tables["concentration_v4"], base_scenarios,
        float(settings.section("v4_research")["replacement_cost_turnover_cap_ratio"]),
        int(settings.section("v4_research")["maximum_pressure_candidates"]),
    )
    _write_both(selection, root / "candidate_selection_v4")
    _write_both(
        _skip_recent_impact(tables["scenario_metrics_v4"], tables["concentration_v4"]),
        root / "skip_recent_impact_v4",
    )
    pressure = tables["scenario_metrics_v4"][
        tables["scenario_metrics_v4"]["实验阶段"].eq("05_pressure")
    ]
    _write_both(pressure, root / "slippage_pressure_v4")
    recommendation = _recommendation_table(
        tables["scenario_metrics_v4"], tables["robustness_v4"],
        tables["concentration_v4"], selection, base_scenarios,
    )
    _write_both(recommendation, root / "final_recommendation_v4")
    _write_both(
        _v3_v4_comparison(
            tables["scenario_metrics_v4"], tables["concentration_v4"],
            recommendation, base_scenarios,
        ),
        root / "v3_v4_comparison",
    )
    reconciliation, execution = _accounting_audit_all(
        results, scenarios, tables["pnl_contribution_v4"], initial
    )
    _write_both(reconciliation, root / "accounting_reconciliation_v4")
    _write_both(execution, root / "execution_audit_statistics_v4")

    # This rebuild is read-only with respect to the frozen cache.  It only adds
    # the aggregate multi-period forecast distribution omitted by the first pass.
    library = build_forecast_library_v4(settings, data)
    _save_forecast_library(root, library, settings)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["recommended_label"] = recommendation.iloc[0]["推荐标签"]
    manifest["retain_v3"] = bool(recommendation.iloc[0]["是否保留v3"])
    manifest["analytics_rebuilt_for_v3_turnover_definition"] = True
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    from five_sector_momentum.reports_v4 import write_engine_audit_v4, write_result_report_v4
    write_engine_audit_v4(settings, data, root)
    write_result_report_v4(settings, root)
    _write_both(_traceability(root), root / "pickle_csv_traceability_v4")
    print(f"v4 analytics finalized: {root}")


def _scenario_from_row(row: pd.Series) -> V4Scenario:
    def optional_int(value):
        return None if pd.isna(value) else int(value)
    return V4Scenario(
        label=str(row["label"]), stage=str(row["stage"]), family=str(row["family"]),
        horizons=tuple(int(item) for item in str(row["horizons"]).split(",")),
        aggregation=str(row["aggregation"]), skip_recent_days=int(row["skip_recent_days"]),
        effective_window_days=optional_int(row["effective_window_days"]),
        candidate=bool(row["candidate"]),
        parent_label=None if pd.isna(row["parent_label"]) else str(row["parent_label"]),
        omitted_horizon=optional_int(row["omitted_horizon"]),
        slippage_model=str(row["slippage_model"]),
        fixed_slippage_ticks=float(row["fixed_slippage_ticks"]),
    )


def _load_result(root: Path, scenario: V4Scenario) -> BacktestResult:
    directory = root / scenario.name
    frames = {
        name: pd.read_pickle(directory / f"{filename}.pkl")
        for name, filename in [
            ("equity", "daily_equity"), ("positions", "positions"),
            ("targets", "targets"), ("orders", "orders"), ("fills", "fills"),
            ("rejections", "rejections"), ("pnl_by_instrument", "pnl_by_instrument"),
        ]
    }
    diagnostics = json.loads((directory / "diagnostics.json").read_text(encoding="utf-8"))
    return BacktestResult(scenario=scenario.execution_scenario(), diagnostics=diagnostics, **frames)


if __name__ == "__main__":
    main()
