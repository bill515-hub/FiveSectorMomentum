from __future__ import annotations

import math
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.analytics import sector_contribution
from five_sector_momentum.data_pipeline import DataBundle, build_panama_prices
from five_sector_momentum.engine import BacktestEngine, BacktestResult, BacktestScenario, buffered_position
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import build_signals, robust_price_volatility


ROOT = Path(__file__).resolve().parents[1]


def settings() -> Settings:
    return Settings.load(ROOT / "configs" / "five_sector_momentum.yaml")


class BufferTests(unittest.TestCase):
    def test_zero_buffer_returns_exact_target(self) -> None:
        self.assertEqual(buffered_position(95, 100, 0.0), 100)

    def test_inside_buffer_does_not_trade(self) -> None:
        self.assertEqual(buffered_position(95, 100, 0.10), 95)
        self.assertEqual(buffered_position(110, 100, 0.10), 110)

    def test_outside_buffer_trades_to_nearest_edge(self) -> None:
        self.assertEqual(buffered_position(70, 100, 0.10), 90)
        self.assertEqual(buffered_position(130, 100, 0.10), 110)
        self.assertEqual(buffered_position(-70, -100, 0.10), -90)
        self.assertEqual(buffered_position(10, 0, 0.10), 0)


class AttributionTests(unittest.TestCase):
    def test_roll_day_slippage_is_allocated_by_contract_once(self) -> None:
        date = pd.Timestamp("2024-01-02")
        result = BacktestResult(
            scenario=BacktestScenario(0.275, "cancel_recalculate", 2.0),
            equity=pd.DataFrame(), positions=pd.DataFrame(), targets=pd.DataFrame(),
            orders=pd.DataFrame(), rejections=pd.DataFrame(), diagnostics={},
            fills=pd.DataFrame([
                {"date": date, "instrument": "RB", "contract": "RB2401.SHF", "slippage_cost": 2.0},
                {"date": date, "instrument": "RB", "contract": "RB2405.SHF", "slippage_cost": 3.0},
            ]),
            pnl_by_instrument=pd.DataFrame([
                {"date": date, "instrument": "RB", "contract": "RB2401.SHF", "sector": "ferrous",
                 "gross_pnl": 8.0, "commission": 1.0, "net_pnl": 7.0},
                {"date": date, "instrument": "RB", "contract": "RB2405.SHF", "sector": "ferrous",
                 "gross_pnl": 17.0, "commission": 1.0, "net_pnl": 16.0},
            ]),
        )
        contribution = sector_contribution(result, 100.0, "2022-01-01")
        full = contribution[contribution["阶段"].eq("全样本")].iloc[0]
        self.assertEqual(full["滑点成本_元"], 5.0)
        self.assertEqual(full["交易成本前盈亏_元"], 30.0)
        self.assertEqual(full["净利润_元"], 23.0)


class PanamaTests(unittest.TestCase):
    def test_panama_adds_forward_minus_price_to_history(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=4)
        bars = pd.DataFrame(
            [
                {"date": dates[0], "ts_code": "X01.DCE", "instrument": "X", "close": 100.0},
                {"date": dates[1], "ts_code": "X01.DCE", "instrument": "X", "close": 101.0},
                {"date": dates[1], "ts_code": "X05.DCE", "instrument": "X", "close": 110.0},
                {"date": dates[2], "ts_code": "X05.DCE", "instrument": "X", "close": 111.0},
                {"date": dates[3], "ts_code": "X05.DCE", "instrument": "X", "close": 112.0},
            ]
        )
        mapping = pd.DataFrame(
            {"date": dates, "instrument": "X", "contract": ["X01.DCE", "X01.DCE", "X05.DCE", "X05.DCE"], "source": "test"}
        )
        _, adjusted, diagnostics = build_panama_prices(settings(), bars, mapping)
        np.testing.assert_allclose(adjusted["adjusted_price"], [109.0, 110.0, 111.0, 112.0])
        self.assertEqual(diagnostics["roll_count"], 1)
        self.assertEqual(diagnostics["stitch_failures"], [])


class SignalTests(unittest.TestCase):
    def test_price_diff_sharpe_and_weekly_selection(self) -> None:
        bundle = synthetic_bundle()
        signal_bundle = build_signals(settings(), bundle)
        last_date = signal_bundle.selections["signal_date"].max()
        selected = signal_bundle.selections[signal_bundle.selections["signal_date"] == last_date]
        directions = dict(zip(selected["instrument"], selected["direction"]))
        self.assertEqual(directions["A"], 1)
        self.assertEqual(directions["C"], -1)
        self.assertEqual(directions["L"], 1)
        self.assertEqual(directions["V"], -1)
        self.assertEqual(directions["RB"], 1)
        self.assertEqual(directions["T"], -1)
        self.assertEqual(directions["AL"], 1)

    def test_robust_volatility_uses_price_points(self) -> None:
        changes = pd.DataFrame({"X": [1.0, -1.0] * 100})
        config = settings().section("volatility").copy()
        config["floor_enabled"] = False
        result = robust_price_volatility(changes, config)
        self.assertGreater(result["X"].dropna().iloc[-1], 0.9)
        self.assertLess(result["X"].dropna().iloc[-1], 1.2)

    def test_future_prices_do_not_change_past_scores_or_directions(self) -> None:
        original = synthetic_bundle()
        cutoff = original.adjusted_prices["date"].sort_values().unique()[-40]
        changed = synthetic_bundle()
        future = changed.adjusted_prices["date"] > cutoff
        changed.adjusted_prices.loc[future, "adjusted_price"] += 1_000_000.0
        first = build_signals(settings(), original)
        second = build_signals(settings(), changed)
        left_scores = first.scores[first.scores["date"] <= cutoff].reset_index(drop=True)
        right_scores = second.scores[second.scores["date"] <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(left_scores, right_scores)
        left_directions = first.directions[first.directions["date"] <= cutoff].reset_index(drop=True)
        right_directions = second.directions[second.directions["date"] <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(left_directions, right_directions)


class EngineTests(unittest.TestCase):
    def test_end_to_end_engine_creates_fills_and_equity(self) -> None:
        config = settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngine(config, bundle, signals)
        result = engine.run(BacktestScenario(0.25, "cancel_recalculate", 1.0))
        self.assertFalse(result.equity.empty)
        self.assertFalse(result.fills.empty)
        self.assertTrue((result.equity["equity"] > 0).all())
        self.assertTrue((result.equity["margin_utilization"] <= 0.55).all())

    def test_account_marks_to_settlement_not_signal_close(self) -> None:
        config = settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngine(config, bundle, signals)
        contract = "RB99.TEST"
        date = bundle.bars.loc[bundle.bars["ts_code"].eq(contract), "date"].iloc[1]
        key = (date, contract)
        original_bar = engine.bars.loc[key].copy()
        engine.bars.loc[key, "close"] = float(original_bar["settlement"]) + 1000.0
        previous = float(
            bundle.bars.loc[
                bundle.bars["ts_code"].eq(contract) & bundle.bars["date"].lt(date), "settlement"
            ].iloc[-1]
        )
        pnl, _, _, _ = engine._mark_to_market(date, {contract: 1}, [], {contract: previous})
        expected = (float(original_bar["settlement"]) - previous) * 10.0
        self.assertAlmostEqual(pnl, expected)

    def test_buffer_diagnostics_count_avoided_rebalance(self) -> None:
        config = settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngine(config, bundle, signals)
        desired, diagnostics = engine._apply_position_buffers(
            bundle.mapping["date"].iloc[-1], {"RB99.TEST": 100}, {"RB99.TEST": 95}
        )
        self.assertEqual(desired["RB99.TEST"], 95)
        self.assertEqual(diagnostics["holds"], 1)


def synthetic_bundle() -> DataBundle:
    dates = pd.bdate_range("2014-01-01", periods=520)
    definitions = {
        "A": ("agriculture", "cross_sectional", 1.2),
        "C": ("agriculture", "cross_sectional", -0.9),
        "L": ("chemical_energy", "cross_sectional", 1.0),
        "V": ("chemical_energy", "cross_sectional", -0.7),
        "RB": ("ferrous", "absolute", 0.8),
        "T": ("government_bond", "absolute", -0.05),
        "AL": ("base_metal", "absolute", 1.5),
    }
    instrument_rows = []
    contract_rows = []
    adjusted_rows = []
    mapping_rows = []
    multiple_rows = []
    bar_rows = []
    rng = np.random.default_rng(7)
    for offset, (instrument, (sector, mode, drift)) in enumerate(definitions.items()):
        contract = f"{instrument}99.TEST"
        point_value = 10.0 if instrument != "T" else 10000.0
        tick_size = 1.0 if instrument != "T" else 0.005
        changes = drift + rng.normal(0, max(abs(drift) * 0.3, 0.05), len(dates))
        base_price = 100.0 if instrument == "T" else 5000 + offset * 1000
        raw = base_price + np.cumsum(changes)
        instrument_rows.append(
            {"instrument": instrument, "exchange": "TEST", "sector": sector, "mode": mode,
             "continuous_code": instrument, "fallback_point_value": point_value,
             "fallback_tick_size": tick_size, "fallback_margin_rate": 0.10}
        )
        contract_rows.append(
            {"ts_code": contract, "instrument": instrument, "exchange": "TEST", "name": instrument,
             "list_date": dates[0], "delist_date": dates[-1] + pd.Timedelta(days=365),
             "point_value": point_value, "tick_size": tick_size,
             "fallback_margin_rate": 0.10, "sector": sector, "mode": mode}
        )
        for date, close in zip(dates, raw):
            open_price = close - drift * 0.25
            bar_rows.append(
                {"date": date, "ts_code": contract, "instrument": instrument,
                 "open": open_price, "high": max(open_price, close) + tick_size,
                 "low": min(open_price, close) - tick_size, "close": close,
                 "settlement": close, "volume": 100000, "oi": 50000,
                 "point_value": point_value, "tick_size": tick_size,
                 "fallback_margin_rate": 0.10, "long_margin_rate": 0.10,
                 "short_margin_rate": 0.10}
            )
            adjusted_rows.append({"date": date, "instrument": instrument, "adjusted_price": close})
            mapping_rows.append({"date": date, "instrument": instrument, "contract": contract, "source": "test"})
            multiple_rows.append(
                {"date": date, "instrument": instrument, "PRICE": close, "PRICE_CONTRACT": contract,
                 "FORWARD": np.nan, "FORWARD_CONTRACT": None, "mapping_source": "test"}
            )
    return DataBundle(
        bars=pd.DataFrame(bar_rows), mapping=pd.DataFrame(mapping_rows),
        multiple_prices=pd.DataFrame(multiple_rows), adjusted_prices=pd.DataFrame(adjusted_rows),
        contract_meta=pd.DataFrame(contract_rows), instrument_meta=pd.DataFrame(instrument_rows),
        diagnostics={"mapping": {}, "panama": {"roll_count": 0, "stitch_failures": []}},
    )


if __name__ == "__main__":
    unittest.main()
