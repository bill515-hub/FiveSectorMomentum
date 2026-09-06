from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.engine_v3 import (
    BacktestEngineV3, BacktestScenarioV3, PendingOrderV3,
    apply_trade_to_lot_ledger,
)
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import build_signals
from five_sector_momentum.analytics_v3 import yearly_table
from test_core import synthetic_bundle


ROOT = Path(__file__).resolve().parents[1]


def v3_settings() -> Settings:
    return Settings.load(ROOT / "configs" / "five_sector_momentum_v3.yaml")


def fee_rules(instruments: list[str], switch: bool = False) -> pd.DataFrame:
    rows = []
    counter = 0
    for instrument in instruments:
        periods = [
            (pd.Timestamp("1900-01-01"), pd.Timestamp("2020-12-31"), 2.0),
            (pd.Timestamp("2021-01-01"), pd.Timestamp("2099-12-31"), 3.0),
        ] if switch else [(pd.Timestamp("1900-01-01"), pd.Timestamp("2099-12-31"), 3.0)]
        for start, end, per_lot in periods:
            for trade_type in ["open", "close_non_today", "close_today"]:
                counter += 1
                rows.append({
                    "rule_id": f"T{counter}", "contract": "*", "instrument": instrument,
                    "exchange": "TEST", "effective_from": start, "effective_to": end,
                    "trade_type": trade_type, "fee_per_lot": per_lot,
                    "fee_rate": 0.0, "source_type": "test", "source_url": "test://fee",
                    "is_proxy": False,
                })
    return pd.DataFrame(rows)


class FeeScheduleTests(unittest.TestCase):
    def test_effective_date_and_client_multiplier(self) -> None:
        schedule = FeeSchedule(fee_rules(["RB"], switch=True))
        old = schedule.charge("RB2001.TEST", "RB", pd.Timestamp("2020-12-31"), "open", 2, 100, 10, 1.5)
        new = schedule.charge("RB2101.TEST", "RB", pd.Timestamp("2021-01-01"), "open", 2, 100, 10, 1.5)
        self.assertEqual(old.exchange_fee, 4.0)
        self.assertEqual(old.client_fee, 6.0)
        self.assertEqual(new.exchange_fee, 6.0)
        self.assertEqual(new.client_fee, 9.0)

    def test_notional_fee_dimension(self) -> None:
        rules = fee_rules(["RB"])
        rules["fee_per_lot"] = 0.0
        rules["fee_rate"] = 0.0001
        charge = FeeSchedule(rules).charge(
            "RB2401.TEST", "RB", pd.Timestamp("2024-01-01"), "open", 2, 3500.0, 10.0, 1.5
        )
        self.assertEqual(charge.exchange_fee, 7.0)
        self.assertEqual(charge.client_fee, 10.5)


class LotClassificationTests(unittest.TestCase):
    def test_cross_zero_splits_close_and_open(self) -> None:
        lots = [{"open_date": pd.Timestamp("2024-01-01"), "quantity": 5}]
        segments = apply_trade_to_lot_ledger(lots, -8, pd.Timestamp("2024-01-02"))
        self.assertEqual(segments, [(-5, "close_non_today"), (-3, "open")])
        self.assertEqual(lots, [{"open_date": pd.Timestamp("2024-01-02"), "quantity": -3}])

    def test_same_day_close_is_distinct(self) -> None:
        lots = [{"open_date": pd.Timestamp("2024-01-02"), "quantity": 5}]
        segments = apply_trade_to_lot_ledger(lots, -3, pd.Timestamp("2024-01-02"))
        self.assertEqual(segments, [(-3, "close_today")])
        self.assertEqual(lots[0]["quantity"], 2)

    def test_roll_has_two_independent_fee_legs(self) -> None:
        schedule = FeeSchedule(fee_rules(["RB"]))
        close = schedule.charge("RB2401.TEST", "RB", pd.Timestamp("2024-01-02"), "close_non_today", 5, 3500, 10, 1.5)
        opened = schedule.charge("RB2405.TEST", "RB", pd.Timestamp("2024-01-02"), "open", 5, 3510, 10, 1.5)
        self.assertEqual(close.client_fee + opened.client_fee, 45.0)


class SlippageTests(unittest.TestCase):
    def test_market_impact_steps_and_adverse_grid(self) -> None:
        self.assertEqual(BacktestEngineV3._impact_ticks(0.01), 0.0)
        self.assertEqual(BacktestEngineV3._impact_ticks(0.01001), 1.0)
        self.assertEqual(BacktestEngineV3._impact_ticks(0.03), 1.0)
        self.assertEqual(BacktestEngineV3._impact_ticks(0.03001), 2.0)
        self.assertEqual(BacktestEngineV3._adverse_grid_price(100.01, 0.2, 1), 100.2)
        self.assertEqual(BacktestEngineV3._adverse_grid_price(100.19, 0.2, -1), 100.0)

    def test_slippage_enters_fill_price_and_is_not_deducted_twice(self) -> None:
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngineV3(
            config, bundle, signals,
            FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist())),
        )
        date = bundle.mapping["date"].iloc[-1]
        contract = "RB99.TEST"
        engine.bars.loc[(date, contract), "open"] = 100.0
        engine.bars.loc[(date, contract), "settlement"] = 105.0
        engine.liquidity[(date, "RB")] = {"median_volume": 100_000.0, "median_open_interest": 50_000.0}
        order = PendingOrderV3(contract, "RB", 1, date, "normal_rebalance", 1)
        scenario = BacktestScenarioV3(
            "hand_calc", "test", fee_multiplier=1.5,
            slippage_model="fixed", fixed_slippage_ticks=2.0,
        )
        fills, remainder, rejection = engine._execute_order_v3(date, order, scenario, {})
        self.assertEqual(remainder, 0)
        self.assertIsNone(rejection)
        self.assertEqual(fills[0]["price"], 102.0)
        self.assertEqual(fills[0]["slippage_cost"], 20.0)
        pnl, fees, _, _ = engine._mark_to_market(date, {}, fills, {})
        self.assertEqual(pnl, 30.0)
        self.assertEqual(fees, 4.5)
        self.assertEqual(pnl - fees, 25.5)

    def test_limit_rejection_uses_open_and_limit_not_future_high_low(self) -> None:
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngineV3(
            config, bundle, signals,
            FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist())),
        )
        date = bundle.mapping["date"].iloc[-1]
        contract = "RB99.TEST"
        open_price = float(engine.bars.loc[(date, contract), "open"])
        engine.bars.loc[(date, contract), "upper_limit"] = open_price
        engine.bars.loc[(date, contract), "high"] = open_price + 100.0
        order = PendingOrderV3(contract, "RB", 1, date, "normal_rebalance", 1)
        fills, remainder, rejection = engine._execute_order_v3(
            date, order, BacktestScenarioV3("limit", "test"), {}
        )
        self.assertEqual(fills, [])
        self.assertEqual(remainder, 1)
        self.assertEqual(rejection["reason"], "adverse_limit_at_open")

    def test_partial_fill_uses_lagged_volume_not_execution_day_final_volume(self) -> None:
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngineV3(
            config, bundle, signals,
            FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist())),
        )
        date = bundle.mapping["date"].iloc[-1]
        contract = "RB99.TEST"
        engine.liquidity[(date, "RB")] = {"median_volume": 10_000.0, "median_open_interest": 50_000.0}
        order = PendingOrderV3(contract, "RB", 800, date, "normal_rebalance", 1)
        first, remainder, rejection = engine._execute_order_v3(
            date, order, BacktestScenarioV3("partial", "test"), {}
        )
        engine.bars.loc[(date, contract), "volume"] = 1.0
        second, second_remainder, _ = engine._execute_order_v3(
            date, order, BacktestScenarioV3("partial", "test"), {}
        )
        self.assertEqual(sum(abs(item["quantity"]) for item in first), 500)
        self.assertEqual(remainder, 300)
        self.assertEqual(rejection["reason"], "partial_fill")
        self.assertEqual(sum(abs(item["quantity"]) for item in second), 500)
        self.assertEqual(second_remainder, 300)


class RebalanceTests(unittest.TestCase):
    def _engine(self):
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        engine = BacktestEngineV3(
            config, bundle, signals,
            FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist())),
        )
        return config, bundle, engine

    def test_signal_exit_bypasses_weekly_schedule_and_buffer(self) -> None:
        _, bundle, engine = self._engine()
        date = next(item for item in bundle.mapping["date"].unique() if item not in engine.weekly_signal_dates)
        engine.directions[(date, "RB")] = 0
        desired, _, reasons = engine._scheduled_targets(
            date, {}, {"RB99.TEST": 100}, 10_000_000.0,
            {"trailing_realized_volatility": 0.10},
            BacktestScenarioV3("weekly_exit", "test", rebalance_mode="weekly", buffer_fraction=0.20),
        )
        self.assertNotIn("RB99.TEST", desired)
        self.assertEqual(reasons["RB99.TEST"], "signal_exit")

    def test_margin_forced_reduction_bypasses_buffer(self) -> None:
        _, bundle, engine = self._engine()
        date = next(item for item in bundle.mapping["date"].unique() if item not in engine.weekly_signal_dates)
        engine.directions[(date, "RB")] = 1
        desired, diagnostics, reasons = engine._scheduled_targets(
            date, {"RB99.TEST": 100_000}, {"RB99.TEST": 100_000}, 1_000_000.0,
            {"trailing_realized_volatility": 0.10},
            BacktestScenarioV3("weekly_margin", "test", rebalance_mode="weekly", buffer_fraction=0.20),
        )
        self.assertLess(abs(desired.get("RB99.TEST", 0)), 100_000)
        self.assertEqual(diagnostics["forced_constraint_days"], 1)
        self.assertEqual(reasons["RB99.TEST"], "margin_forced")


class ReportingTests(unittest.TestCase):
    def test_incomplete_final_year_is_labeled(self) -> None:
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        result = BacktestEngineV3(
            config, bundle, signals,
            FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist())),
        ).run(BacktestScenarioV3("report", "test"))
        final_date = str(result.equity["date"].max().date())
        table = yearly_table(result, 10_000_000.0, final_date)
        self.assertTrue(table.iloc[-1]["年度状态"].startswith("截至"))


class V3IntegrationTests(unittest.TestCase):
    def test_hybrid_engine_is_deterministic_and_auditable(self) -> None:
        config = v3_settings()
        bundle = synthetic_bundle()
        signals = build_signals(config, bundle)
        schedule = FeeSchedule(fee_rules(bundle.instrument_meta["instrument"].tolist()))
        scenario = BacktestScenarioV3("hybrid", "test")
        first = BacktestEngineV3(config, bundle, signals, schedule).run(scenario)
        second = BacktestEngineV3(config, bundle, signals, schedule).run(scenario)
        pd.testing.assert_frame_equal(first.equity, second.equity)
        self.assertFalse(first.fills.empty)
        self.assertTrue(set(first.fills["transaction_type"]).issubset(
            {"open", "close_non_today", "close_today"}
        ))
        self.assertTrue((first.fills["price"] >= 0).all())
        self.assertGreater(first.diagnostics["non_rebalance_days"], 0)


if __name__ == "__main__":
    unittest.main()
