from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.engine_v3 import PendingOrderV3
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4, price_diff_sharpe
from five_sector_momentum.signals_v4_2 import signal_bundle_v42
from five_sector_momentum.v6_2.engine import _CausalExecutionMixin
from five_sector_momentum.v6_3.attempts import finish, start
from five_sector_momentum.v6_3.engine import BacktestEngineV63, ScenarioV63, SleeveEngineV63
from five_sector_momentum.v6_3.preflight import data_contract_audit
from five_sector_momentum.v6_3.registry import EXPECTED_IDS, load, validate
from test_core import synthetic_bundle
from test_v3 import fee_rules
from five_sector_momentum.v6_1.engine import corrected_fee_schedule


ROOT = Path(__file__).resolve().parents[2]


class DummyFee:
    def charge(self, contract, instrument, date, trade_type, lots, price, point_value, multiplier):
        return SimpleNamespace(
            exchange_fee=2.0 * lots, client_fee=3.0 * lots, fee_per_lot=2.0,
            fee_rate=0.0, rule_id="HAND", source_type="HAND", source_url="", is_proxy=True,
        )


def mini_engine(execution_proxy="next_close", settlement=110.0):
    scenario = ScenarioV63("X", "reference_v3_252", execution_proxy, "static_fallback", "fixed_1_tick")
    engine = BacktestEngineV63.__new__(BacktestEngineV63)
    date = pd.Timestamp("2024-01-03")
    contract = "RB2405.SHF"
    engine.v62_scenario = scenario
    engine._cost = scenario.cost()
    engine.bars = pd.DataFrame([{
        "date": date, "contract": contract, "open": 95.0, "close": 100.0,
        "settlement": settlement, "tick_size": 1.0, "point_value": 10.0,
    }]).set_index(["date", "contract"])
    engine.liquidity = {(pd.Timestamp("2024-01-02"), "RB"): {"median_volume": 1000.0, "median_open_interest": 5000.0}}
    engine.execution = {
        "max_volume_participation": 0.05, "fallback_executable_volume": 10000,
        "roll_extra_ticks": 1.0, "high_liquidity_instruments": ["T", "RB", "AL"],
        "high_liquidity_min_median_volume": 10000, "high_liquidity_min_median_open_interest": 20000,
    }
    engine.fee_schedule = DummyFee()
    engine.contract_meta = pd.DataFrame({"instrument": ["RB"]}, index=[contract])
    engine.sector_by_instrument = {"RB": "ferrous"}
    return engine, scenario, date, contract


def execute(engine, scenario, date, contract, quantity, lots):
    order = PendingOrderV3(contract, "RB", quantity, pd.Timestamp("2024-01-02"), "normal_rebalance")
    return engine._execute_order_v3(date, order, scenario.legacy_scenario().execution(), lots)[0]


class RegistryAndDataTests(unittest.TestCase):
    def test_registry_is_exactly_17_scenarios_and_19_attempts(self):
        registry = load(ROOT / "docs/v6_3_three_horizon_and_single_window_plan/V6_3_MACHINE_REGISTRY.yaml")
        self.assertTrue(validate(registry).passed.all())
        self.assertEqual([row["id"] for row in registry["scenario_order"]], EXPECTED_IDS)

    def test_existing_mapping_audit_detects_backward_expiry_transitions(self):
        checks, details = data_contract_audit()
        row = checks.set_index("check").loc["mapped_contract_expiry_non_decreasing"]
        self.assertFalse(bool(row.passed))
        self.assertEqual(int(row.value), 2)
        self.assertEqual(set(details["mapping_backward_expiry_transitions"].instrument), {"SC"})

    def test_execution_acceptance_source_has_no_same_day_final_fields(self):
        source = inspect.getsource(_CausalExecutionMixin._execute_order_v3)
        for forbidden in ['bar.get("high"', 'bar.get("low"', 'bar.get("settlement"', 'bar.get("volume"', 'bar.get("open_interest"']:
            self.assertNotIn(forbidden, source)
        self.assertIn("order.created_date", source)

    def test_attempt_failure_uses_budget_but_not_sequence(self):
        with TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.csv"
            out = Path(folder) / "out"
            one = start(ledger, "G01", 1, out, "R", "S", 19)
            finish(ledger, one, "FAILED", "TEST")
            two = start(ledger, "G01", 1, out, "R", "S", 19)
            finish(ledger, two, "COMPLETED")
            three = start(ledger, "G02", 2, out, "R", "S", 19)
            self.assertEqual([one, two, three], [1, 2, 3])


class SignalBoundaryTests(unittest.TestCase):
    def test_all_registered_regular_windows_use_exact_sample_std(self):
        values = pd.DataFrame({"X": np.arange(1.0, 301.0) + np.sin(np.arange(300.0))})
        for horizon in [20, 40, 60, 90, 120, 180, 250, 252]:
            result = price_diff_sharpe(values, horizon, 252.0, 0)
            sample = values.X.iloc[-horizon:]
            expected = sample.mean() / sample.std(ddof=1) * np.sqrt(252.0)
            self.assertAlmostEqual(result.X.iloc[-1], expected)
            self.assertTrue(result.X.iloc[: horizon - 1].isna().all())

    def test_skip5_window_boundary(self):
        values = pd.DataFrame({"X": np.arange(1.0, 101.0) + np.cos(np.arange(100.0))})
        for horizon in [20, 60]:
            result = price_diff_sharpe(values, horizon, 252.0, 5)
            sample = values.X.shift(5).iloc[-horizon:]
            expected = sample.mean() / sample.std(ddof=1) * np.sqrt(252.0)
            self.assertAlmostEqual(result.X.iloc[-1], expected)
            self.assertTrue(result.X.iloc[: horizon + 4].isna().all())

    def test_future_append_does_not_change_past_forecast(self):
        rng = np.random.default_rng(9)
        base = pd.DataFrame({"X": rng.normal(size=300)})
        extended = pd.concat([base, pd.DataFrame({"X": [1e9, -1e9]})], ignore_index=True)
        for horizon, skip in [(20, 5), (60, 0), (250, 0), (252, 0)]:
            left = price_diff_sharpe(base, horizon, 252.0, skip)
            right = price_diff_sharpe(extended, horizon, 252.0, skip).iloc[: len(base)]
            pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))


class CompleteSettlementTests(unittest.TestCase):
    def test_new_open_gets_execution_day_close_to_settlement(self):
        engine, scenario, date, contract = mini_engine()
        fills = execute(engine, scenario, date, contract, 1, {})
        gross, costs, _, _ = engine._mark_to_market(date, {}, fills, {})
        self.assertEqual(gross, 100.0)
        self.assertEqual(costs, 13.0)

    def test_pure_close_is_not_double_counted(self):
        engine, scenario, date, contract = mini_engine()
        lots = {contract: [{"quantity": 1, "open_date": pd.Timestamp("2024-01-01")} ]}
        fills = execute(engine, scenario, date, contract, -1, lots)
        gross, _, _, _ = engine._mark_to_market(date, {contract: 1}, fills, {contract: 90.0})
        self.assertEqual(gross, 100.0)
        self.assertTrue(all(fill["transaction_type"].startswith("close") for fill in fills))

    def test_cross_zero_splits_close_and_open_and_settles_once(self):
        engine, scenario, date, contract = mini_engine()
        lots = {contract: [{"quantity": 1, "open_date": pd.Timestamp("2024-01-01")} ]}
        fills = execute(engine, scenario, date, contract, -2, lots)
        self.assertEqual([fill["transaction_type"] for fill in fills], ["close_non_today", "open"])
        gross, costs, _, _ = engine._mark_to_market(date, {contract: 1}, fills, {contract: 90.0})
        self.assertEqual(gross, 0.0)
        self.assertEqual(costs, 26.0)


class ThreeSleeveTests(unittest.TestCase):
    @staticmethod
    def calendar():
        dates = pd.date_range("2014-01-01", "2017-01-06")
        frame = pd.DataFrame({"exchange": "TEST", "date": dates, "is_open": [int(d.weekday() < 5) for d in dates]})
        return TradingCalendarV42(frame)

    def test_three_components_each_receive_one_third_and_missing_stays_unused(self):
        settings = Settings.load(ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml")
        data = synthetic_bundle()
        library = build_forecast_library_v4(settings, data)
        cal = self.calendar()
        by = {
            "single_20_skip5": signal_bundle_v42(settings, data, library, library.raw_skip5[20], "single_20_skip5", cal),
            "single_60": signal_bundle_v42(settings, data, library, library.raw_regular[60], "single_60", cal),
            "single_250": signal_bundle_v42(settings, data, library, library.raw_regular[250], "single_250", cal),
        }
        fees = corrected_fee_schedule(fee_rules(data.instrument_meta.instrument.tolist()))
        engine = SleeveEngineV63(settings, data, by, fees, cal)
        date = data.mapping.date.max()
        for bundle in by.values():
            bundle.directions.loc[bundle.directions.date.eq(date), "direction"] = 0
        engine.directions_by_horizon = {
            key: bundle.directions.set_index(["date", "instrument"]).direction.to_dict()
            for key, bundle in by.items()
        }
        scenario = ScenarioV63("X", "sleeve", "vendor_open", "static_fallback", "normal")
        engine._calculate_targets(date, 10_000_000.0, {}, scenario.legacy_scenario().execution(), [])
        internal = pd.DataFrame(engine.internal_target_rows)
        grouped = internal.groupby(["horizon", "sector"]).allocated_annual_risk.sum()
        expected = 10_000_000.0 * 0.275 * 0.20 / 3.0
        np.testing.assert_allclose(grouped.values, expected)
        self.assertTrue((internal.internal_target == 0).all())
        self.assertTrue(np.allclose(internal.unused_annual_risk, internal.allocated_annual_risk))


if __name__ == "__main__":
    unittest.main(verbosity=2)
