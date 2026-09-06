from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.data_pipeline import build_panama_prices
from five_sector_momentum.engine_v4 import BacktestEngineV4, V4Scenario
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import build_signals
from five_sector_momentum.signals_v4 import (
    aggregate_from_library,
    build_forecast_library_v4,
    causal_forecast_scale,
    price_diff_sharpe,
    signal_bundle_from_forecast,
    strict_equal_weight,
)
from test_core import synthetic_bundle
from test_v3 import fee_rules


ROOT = Path(__file__).resolve().parents[1]


def v4_settings() -> Settings:
    return Settings.load(ROOT / "configs" / "five_sector_momentum_v4.yaml")


class ForecastFormulaV4Tests(unittest.TestCase):
    def test_hand_calculation_and_skip_boundary(self) -> None:
        changes = pd.DataFrame({"X": np.arange(1.0, 13.0)})
        actual = price_diff_sharpe(changes, 4, annualization_days=252.0, skip_recent_days=2)
        expected_window = pd.Series([5.0, 6.0, 7.0, 8.0])
        expected = expected_window.mean() / expected_window.std(ddof=1) * np.sqrt(252.0)
        self.assertAlmostEqual(actual.loc[9, "X"], expected)
        self.assertTrue(actual.loc[:4, "X"].isna().all())

    def test_twelve_minus_one_uses_230_changes_ending_t_minus_20(self) -> None:
        changes = pd.DataFrame({"X": np.arange(1.0, 301.0)})
        actual = price_diff_sharpe(changes, 230, skip_recent_days=20)
        # At row 280, shift(20) ends at original row 260; the 230-row
        # inclusive window is original rows 31..260 (values 32..261 here).
        expected_window = pd.Series(np.arange(32.0, 262.0))
        expected = expected_window.mean() / expected_window.std(ddof=1) * np.sqrt(252.0)
        self.assertAlmostEqual(actual.loc[280, "X"], expected)

    def test_scaling_is_lagged_and_future_append_is_invariant(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=10)
        raw = pd.DataFrame({"A": np.arange(1.0, 11.0), "B": np.arange(2.0, 12.0)}, index=dates)
        scaled, scalar = causal_forecast_scale(raw, 10.0, 3, 0.1, 100.0, 20.0)
        expected_history = raw.iloc[:3].abs().mean(axis=1).mean()
        self.assertAlmostEqual(scalar.iloc[3], 10.0 / expected_history)
        changed = raw.copy()
        changed.loc[dates[-2]:, :] = 1_000_000.0
        scaled_changed, scalar_changed = causal_forecast_scale(changed, 10.0, 3, 0.1, 100.0, 20.0)
        pd.testing.assert_series_equal(scalar.loc[:dates[-2]], scalar_changed.loc[:dates[-2]])
        pd.testing.assert_frame_equal(scaled.loc[:dates[-3]], scaled_changed.loc[:dates[-3]])

    def test_multi_period_missing_component_does_not_dynamic_weight(self) -> None:
        left = pd.DataFrame({"X": [2.0, 4.0], "Y": [3.0, 5.0]})
        right = pd.DataFrame({"X": [6.0, np.nan], "Y": [np.nan, 7.0]})
        combined = strict_equal_weight([left, right])
        self.assertEqual(combined.loc[0, "X"], 4.0)
        self.assertTrue(np.isnan(combined.loc[1, "X"]))
        self.assertTrue(np.isnan(combined.loc[0, "Y"]))

    def test_future_prices_do_not_change_any_past_v4_forecast(self) -> None:
        settings = v4_settings()
        original = synthetic_bundle()
        cutoff = original.adjusted_prices["date"].sort_values().unique()[-40]
        changed = deepcopy(original)
        future = changed.adjusted_prices["date"] > cutoff
        changed.adjusted_prices.loc[future, "adjusted_price"] += 1_000_000.0
        first = build_forecast_library_v4(settings, original)
        second = build_forecast_library_v4(settings, changed)
        for horizon in settings.section("v4_research")["single_horizons"]:
            pd.testing.assert_frame_equal(
                first.raw_regular[horizon].loc[:cutoff], second.raw_regular[horizon].loc[:cutoff]
            )
            pd.testing.assert_frame_equal(
                first.raw_skip5[horizon].loc[:cutoff], second.raw_skip5[horizon].loc[:cutoff]
            )
            pd.testing.assert_frame_equal(
                first.scaled_regular[horizon].loc[:cutoff], second.scaled_regular[horizon].loc[:cutoff]
            )
            pd.testing.assert_series_equal(
                first.scalars[horizon].loc[:cutoff], second.scalars[horizon].loc[:cutoff]
            )


class SignalAndPanamaV4Tests(unittest.TestCase):
    def test_v4_reference_252_exactly_reproduces_v3_signal(self) -> None:
        bundle = synthetic_bundle()
        old = build_signals(Settings.load(ROOT / "configs" / "five_sector_momentum_v3.yaml"), bundle)
        settings = v4_settings()
        library = build_forecast_library_v4(settings, bundle)
        new = signal_bundle_from_forecast(settings, bundle, library, library.raw_reference_252, "reference")
        pd.testing.assert_frame_equal(old.scores, new.scores)
        pd.testing.assert_frame_equal(old.selections, new.selections)
        pd.testing.assert_frame_equal(old.directions, new.directions)

    def test_missing_cross_sectional_forecast_is_not_future_filled(self) -> None:
        settings = v4_settings()
        bundle = synthetic_bundle()
        library = build_forecast_library_v4(settings, bundle)
        forecast = library.raw_regular[20].copy()
        # Use an actual final date of a week and remove one agricultural member.
        candidate = forecast.groupby(forecast.index.to_period("W-FRI")).tail(1).index[-3]
        forecast.loc[candidate, "A"] = np.nan
        bundle_signal = signal_bundle_from_forecast(settings, bundle, library, forecast, "missing")
        selections = bundle_signal.selections[bundle_signal.selections["signal_date"].eq(candidate)]
        self.assertNotIn("A", set(selections["instrument"]))

    def test_appending_future_roll_preserves_past_panama_differences(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=6)
        bars = pd.DataFrame([
            {"date": dates[0], "ts_code": "X01.DCE", "instrument": "X", "close": 100.0},
            {"date": dates[1], "ts_code": "X01.DCE", "instrument": "X", "close": 101.0},
            {"date": dates[1], "ts_code": "X05.DCE", "instrument": "X", "close": 110.0},
            {"date": dates[2], "ts_code": "X05.DCE", "instrument": "X", "close": 111.0},
            {"date": dates[3], "ts_code": "X05.DCE", "instrument": "X", "close": 112.0},
            {"date": dates[3], "ts_code": "X09.DCE", "instrument": "X", "close": 130.0},
            {"date": dates[4], "ts_code": "X09.DCE", "instrument": "X", "close": 131.0},
            {"date": dates[5], "ts_code": "X09.DCE", "instrument": "X", "close": 132.0},
        ])
        first_mapping = pd.DataFrame({
            "date": dates[:4], "instrument": "X",
            "contract": ["X01.DCE", "X01.DCE", "X05.DCE", "X05.DCE"], "source": "test",
        })
        full_mapping = pd.DataFrame({
            "date": dates, "instrument": "X",
            "contract": ["X01.DCE", "X01.DCE", "X05.DCE", "X05.DCE", "X09.DCE", "X09.DCE"],
            "source": "test",
        })
        _, first, _ = build_panama_prices(v4_settings(), bars, first_mapping)
        _, full, _ = build_panama_prices(v4_settings(), bars, full_mapping)
        cutoff = dates[3]
        first_diff = first.set_index("date")["adjusted_price"].diff().loc[:cutoff]
        full_diff = full.set_index("date")["adjusted_price"].diff().loc[:cutoff]
        pd.testing.assert_series_equal(first_diff, full_diff)


class V4EngineIntegrationTests(unittest.TestCase):
    def _run_reference(self):
        settings = v4_settings()
        bundle = synthetic_bundle()
        library = build_forecast_library_v4(settings, bundle)
        signals = signal_bundle_from_forecast(settings, bundle, library, library.raw_reference_252, "reference")
        schedule = FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist()))
        scenario = V4Scenario("reference_v3_252", "00_reference", "reference", (252,), candidate=False)
        return BacktestEngineV4(settings, bundle, signals, schedule).run_v4(scenario)

    def test_orders_are_filled_no_earlier_than_next_trading_day(self) -> None:
        result = self._run_reference()
        created = result.orders.groupby(["contract", "instrument", "quantity"])["created_date"].min()
        self.assertFalse(result.fills.empty)
        for _, fill in result.fills.iterrows():
            matching = result.orders[
                result.orders["contract"].eq(fill["contract"])
                & result.orders["instrument"].eq(fill["instrument"])
            ]
            self.assertTrue((matching["created_date"] < fill["date"]).any())

    def test_reference_engine_is_deterministic_and_accounting_balances(self) -> None:
        first = self._run_reference()
        second = self._run_reference()
        pd.testing.assert_frame_equal(first.equity, second.equity)
        pd.testing.assert_frame_equal(first.fills, second.fills)
        initial = float(v4_settings().section("run")["initial_capital"])
        self.assertAlmostEqual(first.equity["equity"].iloc[-1], initial + first.equity["net_pnl"].sum(), places=6)
        self.assertAlmostEqual(first.equity["fees"].sum(), first.fills["commission"].sum(), places=6)
        self.assertTrue(set(first.fills["transaction_type"]).issubset(
            {"open", "close_non_today", "close_today"}
        ))


if __name__ == "__main__":
    unittest.main()
