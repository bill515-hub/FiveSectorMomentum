from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

import numpy as np
import pandas as pd

from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.data_pipeline import DataBundle
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4, price_diff_sharpe
from five_sector_momentum.signals_v4_2 import signal_bundle_v42
from five_sector_momentum.v6_1.engine import corrected_fee_schedule
from five_sector_momentum.v6_2.margin import LaggedMarginTable

from .attempts import exclusive_lock, finish, start
from .canonical import file_hash, write_pair
from .data import load_corrected_bundle
from .engine import BacktestEngineV63, ScenarioV63, SleeveEngineV63, WATERMARK
from .registry import load


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_MACHINE_REGISTRY.yaml"
FREEZE_PATH = ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_REGISTRY_FREEZE.json"
LEDGER_PATH = ROOT / "outputs/V6_3A_GLOBAL_ATTEMPT_LEDGER.csv"
LOCK_PATH = ROOT / "outputs/.v6_3a_global_attempt.lock"
CONFIG_PATH = ROOT / "configs/five_sector_momentum_v6_3a.yaml"


def _scenario_record(scenario_id: str) -> dict[str, Any]:
    return next(row for row in load(REGISTRY_PATH)["scenario_order"] if row["id"] == scenario_id)


def _assert_frozen() -> dict[str, Any]:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    checks = [(REGISTRY_PATH, freeze["registry_file_sha256"]),
              (CONFIG_PATH, freeze["resolved_config_file_sha256"])]
    for item in freeze["source_hashes"] + freeze["input_hashes"]:
        checks.append((ROOT / item["path"], item["sha256"]))
    for path, expected in checks:
        if not path.exists() or file_hash(path) != expected:
            raise RuntimeError(f"V6_3A_FROZEN_HASH_CHANGED:{path}")
    return freeze


def _load_context() -> tuple[Settings, DataBundle, TradingCalendarV42, dict, Any, LaggedMarginTable]:
    settings = Settings.load(ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml")
    data = load_corrected_bundle(settings)
    library = build_forecast_library_v4(settings, data)
    annualization = float(settings.section("signal")["annualization_days"])
    for horizon in [20, 40, 60, 90, 120, 180, 250]:
        library.raw_regular[horizon] = price_diff_sharpe(library.price_changes, horizon, annualization, 0)
    for horizon in [20, 60]:
        library.raw_skip5[horizon] = price_diff_sharpe(library.price_changes, horizon, annualization, 5)
    library.raw_reference_252 = price_diff_sharpe(library.price_changes, 252, annualization, 0)
    calendar = TradingCalendarV42.load(ROOT / settings.section("v4_2_research")["calendar_path"])
    forecasts = {
        "reference_v3_252": library.raw_reference_252,
        **{f"single_{h}": library.raw_regular[h] for h in [20, 40, 60, 90, 120, 180, 250]},
        "single_20_skip5": library.raw_skip5[20],
        "single_60_skip5": library.raw_skip5[60],
    }
    signals = {
        name: signal_bundle_v42(settings, data, library, frame, name, calendar)
        for name, frame in forecasts.items()
    }
    rules = pd.read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
    fees = corrected_fee_schedule(rules)
    margin_rules = pd.read_pickle(ROOT / "data/v6_2/margin_normalized_rules.pkl")
    margin_table = LaggedMarginTable(margin_rules, sorted(data.mapping.date.unique()), 5)
    return settings, data, calendar, signals, fees, margin_table


def _components(strategy: str, signals: dict) -> dict:
    if strategy == "sleeve_20skip5_250_equal_risk":
        return {key: signals[key] for key in ["single_20_skip5", "single_250"]}
    if strategy == "sleeve_20skip5_60_250_equal_risk":
        return {key: signals[key] for key in ["single_20_skip5", "single_60", "single_250"]}
    raise KeyError(strategy)


def _post_trade_shape_diagnostics(result, data: DataBundle, scenario_id: str) -> pd.DataFrame:
    bars = data.bars.rename(columns={"ts_code": "contract"}).set_index(["date", "contract"])
    rows: list[dict[str, Any]] = []
    for event_type, frame, quantity_name in [
        ("FILL", result.fills, "quantity"), ("REJECTION", result.rejections, "quantity_remaining")
    ]:
        if frame.empty:
            continue
        for item in frame.to_dict("records"):
            key = (pd.Timestamp(item["date"]), item["contract"])
            if key not in bars.index:
                continue
            bar = bars.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            high, low = bar.get("high", np.nan), bar.get("low", np.nan)
            if np.isfinite(high) and np.isfinite(low) and float(high) == float(low):
                rows.append({
                    "scenario_id": scenario_id, "event_type": event_type, "date": key[0],
                    "created_date": item.get("created_date"), "contract": item["contract"],
                    "instrument": item.get("instrument"), "quantity": item.get(quantity_name),
                    "high": high, "low": low, "reason": item.get("reason", ""),
                    "classification": "POST_TRADE_ONE_PRICE_SHAPE_NOT_LIMIT_TRUTH",
                })
    return pd.DataFrame(rows)


def _run_one(row: dict[str, Any], context) -> tuple[Any, DataBundle, Any, dict[str, pd.DataFrame]]:
    settings, data, calendar, signals, fees, margin_table = context
    spec = ScenarioV63(row["id"], row["strategy"], row["execution"], row["margin_mode"], row["slippage"])
    extra: dict[str, pd.DataFrame] = {}
    strategy = row["strategy"]
    if strategy.startswith("sleeve_"):
        components = _components(strategy, signals)
        engine = SleeveEngineV63(settings, data, components, fees, calendar)
        result = engine.run_v63(spec, margin_table)
        extra.update({
            "internal_targets": pd.DataFrame(engine.internal_target_rows),
            "net_target_stages": pd.DataFrame(engine.net_target_rows),
            "risk_stages": pd.DataFrame(engine.risk_rows),
        })
        for name, signal in components.items():
            extra[f"component_scores_{name}"] = signal.scores
            extra[f"component_directions_{name}"] = signal.directions
            extra[f"component_selections_{name}"] = signal.selections
    else:
        signal = signals[strategy]
        engine = BacktestEngineV63(settings, data, signal, fees, calendar)
        result = engine.run_v63(spec, margin_table)
        extra.update({"scores": signal.scores, "selections": signal.selections, "directions": signal.directions})
    extra["margin_engine_usage"] = engine.margin_usage_frame()
    extra["margin_constraint_events"] = pd.DataFrame(engine.margin_constraint_rows)
    extra["post_trade_one_price_shape_diagnostics"] = _post_trade_shape_diagnostics(result, data, row["id"])
    return settings, data, result, extra


def _accounting(scenario_id: str, result, initial: float) -> pd.DataFrame:
    equity, fills, pnl = result.equity.copy(), result.fills.copy(), result.pnl_by_instrument.copy()
    previous = equity.equity.shift().fillna(initial)
    cash = fills.get("cash_slippage_cost", pd.Series(0.0, index=fills.index)).fillna(0.0)
    embedded = fills.get("embedded_slippage_cost", pd.Series(0.0, index=fills.index)).fillna(0.0)
    checks = {
        "daily_equity_increment": float((equity.equity - previous - equity.net_pnl).abs().max()),
        "terminal_equity": float(abs(equity.net_pnl.sum() - (equity.equity.iloc[-1] - initial))),
        "gross_less_cost_equals_net": float((equity.gross_pnl - equity.fees - equity.net_pnl).abs().max()),
        "fills_cost_equals_equity_cost": float(abs(fills.commission.sum() + cash.sum() - equity.fees.sum())),
        "instrument_pnl_equals_equity": float(abs(pnl.net_pnl.sum() - equity.net_pnl.sum())),
        "client_fee_equals_exchange_x1p5": float(abs(fills.commission.sum() - fills.exchange_commission.sum() * 1.5)),
        "next_day_execution": float((pd.to_datetime(fills.date) <= pd.to_datetime(fills.created_date)).sum()),
        "embedded_slippage_zero": float(embedded.abs().sum()),
        "cash_slippage_unique": float(abs(cash.sum() - fills.get("slippage_cost", cash).sum())),
    }
    return pd.DataFrame([{
        "scenario_id": scenario_id, "check": key, "error": value,
        "tolerance": 0.01, "passed": value <= 0.01,
    } for key, value in checks.items()])


def _save(result, path: Path, extra: dict[str, pd.DataFrame]) -> None:
    path.mkdir(parents=True, exist_ok=False)
    for name, frame in [
        ("daily_equity", result.equity), ("positions", result.positions),
        ("targets", result.targets), ("orders", result.orders), ("fills", result.fills),
        ("rejections", result.rejections), ("pnl_by_instrument", result.pnl_by_instrument),
    ]:
        write_pair(frame, path / name)
    for name, frame in extra.items():
        write_pair(frame, path / name)
    (path / "diagnostics.json").write_text(
        json.dumps(result.diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def run_registered(run_root: Path, selected: list[str] | None = None) -> int:
    freeze = _assert_frozen()
    registry = load(REGISTRY_PATH)
    rows = registry["scenario_order"]
    if selected:
        wanted = set(selected)
        rows = [row for row in rows if row["id"] in wanted]
    context = _load_context()
    run_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        scenario_id = row["id"]
        _assert_frozen()
        with exclusive_lock(LOCK_PATH):
            attempt = start(
                LEDGER_PATH, scenario_id, int(row["sequence"]), run_root,
                freeze["registry_file_sha256"], freeze["source_bundle_sha256"], 19,
            )
        try:
            settings, _, result, extra = _run_one(row, context)
            accounting = _accounting(scenario_id, result, float(settings.section("run")["initial_capital"]))
            extra["accounting_reconciliation"] = accounting
            if not accounting.passed.all():
                raise AssertionError(f"ACCOUNTING_RECONCILIATION_FAILED:{accounting.loc[~accounting.passed].to_dict('records')}")
            if float(result.equity.equity.min()) <= 0:
                raise AssertionError("ACCOUNT_INSOLVENT")
            _assert_frozen()
            destination = run_root / scenario_id
            _save(result, destination, extra)
            parameters = {**row, "attempt": attempt, "registry_sha256": freeze["registry_file_sha256"],
                          "source_bundle_sha256": freeze["source_bundle_sha256"], "research_status": WATERMARK}
            (destination / "scenario_parameters.json").write_text(
                json.dumps(parameters, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with exclusive_lock(LOCK_PATH):
                finish(LEDGER_PATH, attempt, "COMPLETED")
            print(json.dumps({"scenario": scenario_id, "status": "COMPLETED",
                              "ending_equity": float(result.equity.equity.iloc[-1]),
                              "fills": len(result.fills)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            partial = run_root / f"{scenario_id}_FAILED_ATTEMPT_{attempt}"
            partial.mkdir(parents=True, exist_ok=True)
            (partial / "failure.json").write_text(json.dumps({
                "scenario": scenario_id, "exception_class": exc.__class__.__name__,
                "message_code": str(exc)[:2000], "traceback": traceback.format_exc(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            with exclusive_lock(LOCK_PATH):
                finish(LEDGER_PATH, attempt, "FAILED", exc.__class__.__name__)
            print(json.dumps({"scenario": scenario_id, "status": "FAILED",
                              "exception_class": exc.__class__.__name__}, ensure_ascii=False), flush=True)
            return 2
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--scenario", action="append")
    args = parser.parse_args(argv)
    return run_registered(args.run_root.resolve(), args.scenario)


if __name__ == "__main__":
    raise SystemExit(main())

