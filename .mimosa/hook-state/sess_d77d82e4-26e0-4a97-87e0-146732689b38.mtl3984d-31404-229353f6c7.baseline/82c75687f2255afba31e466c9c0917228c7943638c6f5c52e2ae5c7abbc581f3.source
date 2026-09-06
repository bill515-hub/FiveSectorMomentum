"""Create read-only per-horizon signal/selection/target trace for v4.2.

This is an analysis artifact only: it does not run the historical engine and does
not alter any existing v2-v4.2 result.  The trace makes the fixed 10%+10%
internal sleeve budgets auditable at forecast, selection and target levels.
"""
from pathlib import Path
import pandas as pd

from five_sector_momentum.settings import Settings
from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.signals_v4 import build_forecast_library_v4
from five_sector_momentum.signals_v4_2 import signal_bundle_v42


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "outputs" / "v4_2_20260903_091241"
CONFIG = PROJECT / "configs" / "five_sector_momentum_v4_2_repaired.yaml"


def write_pair(frame: pd.DataFrame, stem: str) -> None:
    frame.to_csv(ROOT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    frame.to_pickle(ROOT / f"{stem}.pkl")


def main() -> None:
    settings = Settings.load(CONFIG)
    data = load_bundle(settings)
    calendar = TradingCalendarV42.load(PROJECT / settings.section("v4_2_research")["calendar_path"])
    library = build_forecast_library_v4(settings, data)
    specs = [
        ("single_20_skip5", 20, True, "fast_20_skip5"),
        ("single_250", 250, False, "slow_250"),
    ]
    traces = []
    selections = []
    for label, horizon, skip5, sleeve_label in specs:
        forecast = library.raw_skip5[horizon] if skip5 else library.raw_regular[horizon]
        bundle = signal_bundle_v42(settings, data, library, forecast, label, calendar)
        scores = bundle.scores.rename(columns={"score": "forecast"}).copy()
        scores["horizon"] = horizon
        scores["signal_variant"] = sleeve_label
        traces.append(scores)
        if not bundle.selections.empty:
            sel = bundle.selections.copy()
            sel["horizon"] = horizon
            sel["signal_variant"] = sleeve_label
            selections.append(sel)
    trace = pd.concat(traces, ignore_index=True).sort_values(["date", "horizon", "instrument"])
    write_pair(trace, "sleeve_horizon_forecast_trace_v4_2")
    selection = pd.concat(selections, ignore_index=True) if selections else pd.DataFrame()
    write_pair(selection, "sleeve_horizon_selection_trace_v4_2")

    # Target-level summary uses the already persisted S1/S2 internal targets;
    # there is no second account and no additional execution path here.
    rows = []
    for ident, strategy in [("S1", "strategy_sleeve_20skip5_250_equal_risk"),
                            ("S2", "strategy_sleeve_20skip5_250_equal_risk_fixed_3tick")]:
        internal = pd.read_pickle(ROOT / ident / "internal_targets.pkl") if (ROOT / ident / "internal_targets.pkl").exists() else pd.read_pickle(ROOT / f"{ident}__{strategy}" / "internal_targets.pkl")
        grouped = internal.groupby(["horizon", "sector"], dropna=False).agg(
            dates=("date", "nunique"),
            rows=("date", "size"),
            nonzero_target_rows=("internal_target", lambda x: int((x != 0).sum())),
            gross_target_lots=("internal_target", lambda x: float(x.abs().sum())),
            mean_abs_target_lots=("internal_target", lambda x: float(x.abs().mean())),
            allocated_annual_risk=("allocated_annual_risk", "sum"),
            unused_annual_risk=("unused_annual_risk", "sum"),
        ).reset_index()
        grouped.insert(0, "strategy", strategy)
        grouped.insert(0, "run", ident)
        rows.append(grouped)
    write_pair(pd.concat(rows, ignore_index=True), "sleeve_horizon_target_summary_v4_2")


if __name__ == "__main__":
    main()
