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
from five_sector_momentum.engine_v4_2 import SleeveEngineV42
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4
from five_sector_momentum.signals_v4_2 import signal_bundle_v42
from five_sector_momentum.v6_1.engine import BacktestEngineV61, ScenarioV61, SleeveEngineV61, corrected_fee_schedule

from .attempts import exclusive_lock, finish, start
from .canonical import file_hash, write_pair
from .engine import BacktestEngineV62, ScenarioV62, SleeveEngineV62
from .margin import LaggedMarginTable
from .registry import load


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_MACHINE_REGISTRY.yaml"
FREEZE_PATH = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_REGISTRY_FREEZE.json"
LEDGER_PATH = ROOT / "outputs/V6_2_GLOBAL_ATTEMPT_LEDGER.csv"
LOCK_PATH = ROOT / "outputs/.v6_2_global_attempt.lock"
OLD = {
    "R01": ROOT / "outputs/v6_1_20260906_155224/P03",
    "R02": ROOT / "outputs/v6_1_20260906_155224/P04",
}


def _scenario_record(scenario_id: str) -> dict:
    registry = load(REGISTRY_PATH)
    return next(row for row in registry["scenario_order"] if row["id"] == scenario_id)


def _assert_frozen() -> dict:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if file_hash(REGISTRY_PATH) != freeze["registry_file_sha256"]:
        raise RuntimeError("V6_2_FROZEN_REGISTRY_HASH_CHANGED")
    config_path = ROOT / "configs/five_sector_momentum_v6_2.yaml"
    if file_hash(config_path) != freeze["resolved_config_file_sha256"]:
        raise RuntimeError("V6_2_FROZEN_CONFIG_HASH_CHANGED")
    return freeze


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
    normalized_margin = pd.read_pickle(ROOT / "data/v6_2/margin_normalized_rules.pkl")
    margin_table = LaggedMarginTable(normalized_margin, sorted(data.mapping.date.unique()), 5)
    return settings, data, calendar, signals, rules, margin_table


def _save(result, path: Path, extra: dict[str, pd.DataFrame]) -> None:
    path.mkdir(parents=True, exist_ok=False)
    tables = [
        ("daily_equity", result.equity), ("positions", result.positions),
        ("targets", result.targets), ("orders", result.orders), ("fills", result.fills),
        ("rejections", result.rejections), ("pnl_by_instrument", result.pnl_by_instrument),
    ]
    for name, frame in tables:
        write_pair(frame, path / name)
    for name, frame in extra.items():
        write_pair(frame, path / name)
    (path / "diagnostics.json").write_text(
        json.dumps(result.diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _comparison(scenario_id: str, result) -> pd.DataFrame:
    rows = []
    for name, new in [
        ("orders", result.orders), ("fills", result.fills), ("positions", result.positions),
        ("daily_equity", result.equity), ("pnl_by_instrument", result.pnl_by_instrument),
    ]:
        prior = pd.read_pickle(OLD[scenario_id] / f"{name}.pkl")
        common = sorted((set(new.columns) & set(prior.columns)) - {"scenario"})
        keys = {
            "orders": ["created_date", "contract", "quantity"],
            "fills": ["date", "created_date", "contract", "segment_index"],
            "positions": ["date", "contract"], "daily_equity": ["date"],
            "pnl_by_instrument": ["date", "contract"],
        }[name]
        keys = [key for key in keys if key in common]
        a = new[common].sort_values(keys, kind="mergesort").reset_index(drop=True)
        b = prior[common].sort_values(keys, kind="mergesort").reset_index(drop=True)
        row_equal = len(a) == len(b)
        maximum = 0.0
        values_equal = row_equal
        if row_equal:
            for column in common:
                if pd.api.types.is_numeric_dtype(a[column]) and not pd.api.types.is_bool_dtype(a[column]):
                    delta = (pd.to_numeric(a[column], errors="coerce") - pd.to_numeric(b[column], errors="coerce")).abs()
                    maximum = max(maximum, float(delta.max())) if delta.notna().any() else maximum
                    values_equal &= bool(((delta.fillna(0) <= 0.01) | (a[column].isna() & b[column].isna())).all())
                else:
                    values_equal &= bool((a[column].eq(b[column]) | (a[column].isna() & b[column].isna())).all())
        rows.append({
            "scenario_id": scenario_id, "legacy_scenario": "P03" if scenario_id == "R01" else "P04",
            "table": name, "new_rows": len(a), "old_rows": len(b),
            "max_numeric_abs_diff": maximum if row_equal else np.inf,
            "values_equal": values_equal, "passed": row_equal and values_equal and maximum <= 0.01,
        })
    return pd.DataFrame(rows)


def _accounting(scenario_id: str, result, initial: float) -> pd.DataFrame:
    equity = result.equity.copy()
    fills = result.fills.copy()
    pnl = result.pnl_by_instrument.copy()
    previous = equity.equity.shift().fillna(initial)
    cash = fills.get("cash_slippage_cost", pd.Series(0.0, index=fills.index)).fillna(0.0)
    embedded = fills.get("embedded_slippage_cost", pd.Series(0.0, index=fills.index)).fillna(0.0)
    fill_cost = float(fills.commission.sum() + cash.sum())
    checks = {
        "daily_equity_increment": float((equity.equity - previous - equity.net_pnl).abs().max()),
        "terminal_equity": float(abs(equity.net_pnl.sum() - (equity.equity.iloc[-1] - initial))),
        "gross_less_cost_equals_net": float((equity.gross_pnl - equity.fees - equity.net_pnl).abs().max()),
        "fills_cost_equals_equity_cost": float(abs(fill_cost - equity.fees.sum())),
        "instrument_pnl_equals_equity": float(abs(pnl.net_pnl.sum() - equity.net_pnl.sum())),
        "client_fee_equals_exchange_x1p5": float(abs(fills.commission.sum() - fills.exchange_commission.sum() * 1.5)),
        "next_day_execution": float((pd.to_datetime(fills.date) <= pd.to_datetime(fills.created_date)).sum()),
        "embedded_slippage_zero": float(embedded.abs().sum()) if scenario_id not in {"R01", "R02"} else 0.0,
        "cash_slippage_unique": float(abs(cash.sum() - fills.get("slippage_cost", cash).sum())) if scenario_id not in {"R01", "R02"} else 0.0,
    }
    return pd.DataFrame([
        {"scenario_id": scenario_id, "check": key, "error": value, "tolerance": 0.01, "passed": value <= 0.01}
        for key, value in checks.items()
    ])


def _post_trade_shape_diagnostics(result, data, scenario_id: str) -> pd.DataFrame:
    if "ts_code" not in data.bars.columns:
        raise KeyError("V6_2_EXPECTED_NORMALIZED_BAR_KEY_TS_CODE")
    bars = data.bars.rename(columns={"ts_code": "contract"}).set_index(["date", "contract"])
    rows = []
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
                    "high": high, "low": low, "pre_settle": bar.get("pre_settle", np.nan),
                    "reason": item.get("reason", ""), "classification": "POST_TRADE_ONE_PRICE_SHAPE_NOT_LIMIT_TRUTH",
                })
    return pd.DataFrame(rows)


def _run(scenario_id: str):
    row = _scenario_record(scenario_id)
    settings, data, calendar, signals, rules, margin_table = _load_v42()
    fees = corrected_fee_schedule(rules)
    extra: dict[str, pd.DataFrame] = {}
    if scenario_id in {"R01", "R02"}:
        spec = ScenarioV61(scenario_id, row["strategy"], "p1", "normal", "vendor_open", "corrected")
        if scenario_id == "R01":
            engine = BacktestEngineV61(settings, data, signals["reference_v3_252"], fees, calendar)
            result = engine.run_v61(spec)
            extra.update({"scores": signals["reference_v3_252"].scores, "selections": signals["reference_v3_252"].selections, "directions": signals["reference_v3_252"].directions})
        else:
            components = {"single_20_skip5": signals["single_20_skip5"], "single_250": signals["single_250"]}
            engine = SleeveEngineV61(settings, data, components, fees, calendar)
            result = engine.run_v61(spec)
            extra.update({"internal_targets": pd.DataFrame(engine.internal_target_rows), "net_target_stages": pd.DataFrame(engine.net_target_rows), "risk_stages": pd.DataFrame(engine.risk_rows)})
        extra["one_price_order_events"] = pd.DataFrame(engine.one_price_order_events)
    else:
        spec = ScenarioV62(scenario_id, row["strategy"], row["execution"], row["margin_mode"], row["slippage"])
        if row["strategy"] == "reference_v3_252":
            engine = BacktestEngineV62(settings, data, signals["reference_v3_252"], fees, calendar)
            result = engine.run_v62(spec, margin_table)
            extra.update({"scores": signals["reference_v3_252"].scores, "selections": signals["reference_v3_252"].selections, "directions": signals["reference_v3_252"].directions})
        else:
            components = {"single_20_skip5": signals["single_20_skip5"], "single_250": signals["single_250"]}
            engine = SleeveEngineV62(settings, data, components, fees, calendar)
            result = engine.run_v62(spec, margin_table)
            extra.update({"internal_targets": pd.DataFrame(engine.internal_target_rows), "net_target_stages": pd.DataFrame(engine.net_target_rows), "risk_stages": pd.DataFrame(engine.risk_rows)})
        extra["margin_engine_usage"] = engine.margin_usage_frame()
        extra["margin_constraint_events"] = pd.DataFrame(engine.margin_constraint_rows)
    extra["post_trade_one_price_shape_diagnostics"] = _post_trade_shape_diagnostics(result, data, scenario_id)
    return settings, data, result, extra


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args(argv)
    run_root = args.run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    scenario_id = args.scenario
    row = _scenario_record(scenario_id)
    freeze = _assert_frozen()
    with exclusive_lock(LOCK_PATH):
        attempt = start(LEDGER_PATH, scenario_id, int(row["sequence"]), run_root, freeze["registry_file_sha256"], 14)
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
        if float(result.equity.equity.min()) <= 0:
            raise AssertionError("ACCOUNT_INSOLVENT")
        _save(result, destination, extra)
        params = dict(row)
        params.update({"research_status": "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION", "attempt": attempt, "registry_sha256": freeze["registry_file_sha256"]})
        (destination / "scenario_parameters.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "complete.json").write_text(json.dumps({"complete": True, "accounting_passed": True, "registry_sha256": freeze["registry_file_sha256"]}, indent=2), encoding="utf-8")
        with exclusive_lock(LOCK_PATH):
            finish(LEDGER_PATH, attempt, "COMPLETED")
        print(json.dumps({"scenario": scenario_id, "status": "COMPLETED", "ending_equity": float(result.equity.equity.iloc[-1]), "fills": len(result.fills)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        partial = run_root / f"{scenario_id}_FAILED_ATTEMPT_{attempt}"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "failure.json").write_text(json.dumps({"scenario": scenario_id, "exception_class": exc.__class__.__name__, "message_code": str(exc)[:2000], "traceback": traceback.format_exc()}, ensure_ascii=False, indent=2), encoding="utf-8")
        with exclusive_lock(LOCK_PATH):
            finish(LEDGER_PATH, attempt, "FAILED", exc.__class__.__name__)
        print(json.dumps({"scenario": scenario_id, "status": "FAILED", "exception_class": exc.__class__.__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
