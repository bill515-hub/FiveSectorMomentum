from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

import numpy as np
import pandas as pd

from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.engine_v3 import BacktestEngineV3, BacktestScenarioV3
from five_sector_momentum.engine_v4_1 import COST_SPECS, ScenarioV41
from five_sector_momentum.engine_v4_2 import BacktestEngineV42, SleeveEngineV42
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import build_signals
from five_sector_momentum.signals_v4 import build_forecast_library_v4
from five_sector_momentum.signals_v4_2 import signal_bundle_v42

from .attempts import exclusive_lock, finish, start
from .canonical import file_hash, table_hash, write_pair
from .engine import BacktestEngineV61, ScenarioV61, SleeveEngineV61, corrected_fee_schedule
from .registry import load


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml"
FREEZE_PATH = ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_REGISTRY_FREEZE.json"
LEDGER_PATH = ROOT / "outputs/V6_1_GLOBAL_ATTEMPT_LEDGER.csv"
LOCK_PATH = ROOT / "outputs/.v6_1_global_attempt.lock"
OLD = {
    "R01": ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline",
    "R02": ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk",
}


def _scenario_record(scenario_id: str) -> dict:
    registry = load(REGISTRY_PATH)
    return next(row for row in registry["scenario_order"] if row["id"] == scenario_id)


def _load_v42():
    settings = Settings.load(ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml")
    data = load_bundle(settings)
    library = build_forecast_library_v4(settings, data)
    calendar = TradingCalendarV42.load(ROOT / settings.section("v4_2_research")["calendar_path"])
    signals = {
        "reference_v3_252": signal_bundle_v42(settings, data, library, library.raw_reference_252, "reference_v3_252", calendar),
        "single_20_skip5": signal_bundle_v42(settings, data, library, library.raw_skip5[20], "single_20_skip5", calendar),
        "single_250": signal_bundle_v42(settings, data, library, library.raw_regular[250], "single_250", calendar),
    }
    rules = pd.read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
    return settings, data, calendar, signals, rules


def _save(result, path: Path, extra: dict[str, pd.DataFrame] | None = None) -> None:
    path.mkdir(parents=True, exist_ok=False)
    for name, frame in [("daily_equity", result.equity), ("positions", result.positions),
        ("targets", result.targets), ("orders", result.orders), ("fills", result.fills),
        ("rejections", result.rejections), ("pnl_by_instrument", result.pnl_by_instrument),
    ]:
        write_pair(frame, path / name)
    for name, frame in (extra or {}).items():
        write_pair(frame, path / name)
    (path / "diagnostics.json").write_text(json.dumps(result.diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _comparison(scenario_id: str, result) -> pd.DataFrame:
    old = OLD[scenario_id]
    rows = []
    for name, new in [("orders", result.orders), ("fills", result.fills), ("positions", result.positions), ("daily_equity", result.equity), ("pnl_by_instrument", result.pnl_by_instrument)]:
        prior = pd.read_pickle(old / f"{name}.pkl")
        common = sorted((set(new.columns) & set(prior.columns)) - {"scenario"})
        keys = {"orders": ["created_date", "contract", "quantity"], "fills": ["date", "created_date", "contract", "segment_index"], "positions": ["date", "contract"], "daily_equity": ["date"], "pnl_by_instrument": ["date", "contract"]}[name]
        keys = [k for k in keys if k in common]
        a = new[common].sort_values(keys, kind="mergesort").reset_index(drop=True)
        b = prior[common].sort_values(keys, kind="mergesort").reset_index(drop=True)
        row_equal = len(a) == len(b)
        max_numeric = 0.0; text_equal = True
        if row_equal:
            for column in common:
                if pd.api.types.is_numeric_dtype(a[column]) and not pd.api.types.is_bool_dtype(a[column]):
                    delta = (pd.to_numeric(a[column], errors="coerce") - pd.to_numeric(b[column], errors="coerce")).abs()
                    if delta.notna().any(): max_numeric = max(max_numeric, float(delta.max()))
                    if not ((delta.fillna(0) <= 0.01) | (a[column].isna() & b[column].isna())).all(): text_equal = False
                elif not (a[column].eq(b[column]) | (a[column].isna() & b[column].isna())).all():
                    text_equal = False
        passed = row_equal and max_numeric <= 0.01 and text_equal
        rows.append({"scenario_id": scenario_id, "table": name, "new_rows": len(a), "old_rows": len(b), "max_numeric_abs_diff": max_numeric if row_equal else np.inf, "non_numeric_and_nan_equal": text_equal if row_equal else False, "passed": passed})
    return pd.DataFrame(rows)


def _accounting(scenario_id: str, result, initial: float) -> pd.DataFrame:
    e, f, p = result.equity.copy(), result.fills.copy(), result.pnl_by_instrument.copy()
    prev = e.equity.shift().fillna(initial)
    cash = f.get("cash_slippage_cost", pd.Series(0.0, index=f.index)).fillna(0.0)
    total_fill_cost = float(f.commission.sum() + cash.sum())
    checks = {
        "daily_equity_increment": float((e.equity - prev - e.net_pnl).abs().max()),
        "terminal_equity": float(abs(e.net_pnl.sum() - (e.equity.iloc[-1] - initial))),
        "gross_less_cost_equals_net": float((e.gross_pnl - e.fees - e.net_pnl).abs().max()),
        "fills_cost_equals_equity_cost": float(abs(total_fill_cost - e.fees.sum())),
        "instrument_pnl_equals_equity": float(abs(p.net_pnl.sum() - e.net_pnl.sum())),
        "client_fee_equals_exchange_x1p5": float(abs(f.commission.sum() - f.exchange_commission.sum() * 1.5)),
        "next_day_execution": float((pd.to_datetime(f.date) <= pd.to_datetime(f.created_date)).sum()),
    }
    return pd.DataFrame([{"scenario_id": scenario_id, "check": k, "error": v, "tolerance": 0.01, "passed": v <= 0.01} for k, v in checks.items()])


def _run(scenario_id: str):
    row = _scenario_record(scenario_id)
    if scenario_id == "R01":
        settings = Settings.load(ROOT / "configs/five_sector_momentum_v3.yaml")
        data = load_bundle(settings); signals = build_signals(settings, data)
        fees = FeeSchedule.load(ROOT / "data/v3/fees/historical_fee_rules")
        engine = BacktestEngineV3(settings, data, signals, fees)
        result = engine.run(BacktestScenarioV3("formal_baseline", "00_formal"))
        extra = {"scores": signals.scores, "selections": signals.selections, "directions": signals.directions}
    else:
        settings, data, calendar, signals, rules = _load_v42()
        fees = FeeSchedule(rules)
        if scenario_id == "R02":
            engine = SleeveEngineV42(settings, data, {"single_20_skip5": signals["single_20_skip5"], "single_250": signals["single_250"]}, fees, calendar)
            result = engine.run_v4_2(ScenarioV41("strategy_sleeve_20skip5_250_equal_risk", "S1", COST_SPECS["C3"]))
            extra = {"internal_targets": pd.DataFrame(engine.internal_target_rows), "net_target_stages": pd.DataFrame(engine.net_target_rows), "risk_stages": pd.DataFrame(engine.risk_rows)}
        else:
            fees = corrected_fee_schedule(rules)
            spec = ScenarioV61(scenario_id, row["strategy"], row["one_price_policy"], row["slippage"], row["execution"], row["fee"])
            if row["strategy"] == "reference_v3_252":
                engine = BacktestEngineV61(settings, data, signals["reference_v3_252"], fees, calendar)
                result = engine.run_v61(spec)
                extra = {"scores": signals["reference_v3_252"].scores, "selections": signals["reference_v3_252"].selections, "directions": signals["reference_v3_252"].directions}
            else:
                components = {"single_20_skip5": signals["single_20_skip5"], "single_250": signals["single_250"]}
                engine = SleeveEngineV61(settings, data, components, fees, calendar)
                result = engine.run_v61(spec)
                extra = {"internal_targets": pd.DataFrame(engine.internal_target_rows), "net_target_stages": pd.DataFrame(engine.net_target_rows), "risk_stages": pd.DataFrame(engine.risk_rows)}
            extra["one_price_order_events"] = pd.DataFrame(engine.one_price_order_events)
    return settings, data, result, extra


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args(argv)
    run_root = args.run_root.resolve(); run_root.mkdir(parents=True, exist_ok=True)
    scenario_id = args.scenario; row = _scenario_record(scenario_id)
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    with exclusive_lock(LOCK_PATH):
        attempt = start(LEDGER_PATH, scenario_id, int(row["sequence"]), run_root, freeze["registry_file_sha256"], 16)
    destination = run_root / scenario_id
    try:
        settings, data, result, extra = _run(scenario_id)
        accounting = _accounting(scenario_id, result, float(settings.section("run")["initial_capital"]))
        extra["accounting_reconciliation"] = accounting
        if not accounting.passed.all():
            raise AssertionError(f"ACCOUNTING_RECONCILIATION_FAILED {accounting.loc[~accounting.passed].to_dict('records')}")
        if scenario_id in OLD:
            reproduction = _comparison(scenario_id, result)
            extra["reproduction_gate"] = reproduction
            if not reproduction.passed.all():
                raise AssertionError(f"REPRODUCTION_GATE_FAILED {reproduction.loc[~reproduction.passed].to_dict('records')}")
        _save(result, destination, extra)
        params = dict(row); params.update({"research_status": "PROVISIONAL_DAILY_ONLY", "attempt": attempt, "registry_sha256": freeze["registry_file_sha256"]})
        (destination / "scenario_parameters.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "complete.json").write_text(json.dumps({"complete": True, "accounting_passed": True, "registry_sha256": freeze["registry_file_sha256"]}, indent=2), encoding="utf-8")
        with exclusive_lock(LOCK_PATH): finish(LEDGER_PATH, attempt, "COMPLETED")
        print(json.dumps({"scenario": scenario_id, "status": "COMPLETED", "ending_equity": float(result.equity.equity.iloc[-1]), "fills": len(result.fills)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        partial = run_root / f"{scenario_id}_FAILED_ATTEMPT_{attempt}"; partial.mkdir(parents=True, exist_ok=True)
        (partial / "failure.json").write_text(json.dumps({"scenario": scenario_id, "exception_class": exc.__class__.__name__, "message_code": str(exc)[:2000], "traceback": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        with exclusive_lock(LOCK_PATH): finish(LEDGER_PATH, attempt, "FAILED", exc.__class__.__name__)
        print(json.dumps({"scenario": scenario_id, "status": "FAILED", "exception_class": exc.__class__.__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
