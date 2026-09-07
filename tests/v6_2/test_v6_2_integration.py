from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import pandas as pd

from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4
from five_sector_momentum.signals_v4_2 import signal_bundle_v42
from five_sector_momentum.v6_1.engine import corrected_fee_schedule
from five_sector_momentum.v6_2.engine import BacktestEngineV62, ScenarioV62, SleeveEngineV62
from five_sector_momentum.v6_2.margin import LaggedMarginTable
from test_core import synthetic_bundle
from test_v3 import fee_rules


ROOT = Path(__file__).resolve().parents[2]


def calendar():
    dates = pd.date_range("2014-01-01", "2017-01-06")
    return TradingCalendarV42(pd.DataFrame({"exchange": "TEST", "date": dates, "is_open": [int(d.weekday() < 5) for d in dates]}))


def setup(data=None):
    settings = Settings.load(ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml")
    data = synthetic_bundle() if data is None else data
    library = build_forecast_library_v4(settings, data)
    cal = calendar()
    signals = {
        "reference": signal_bundle_v42(settings, data, library, library.raw_reference_252, "reference_v3_252", cal),
        "single_20_skip5": signal_bundle_v42(settings, data, library, library.raw_skip5[20], "single_20_skip5", cal),
        "single_250": signal_bundle_v42(settings, data, library, library.raw_regular[250], "single_250", cal),
    }
    fees = corrected_fee_schedule(fee_rules(data.instrument_meta.instrument.tolist()))
    empty_margin = pd.DataFrame(columns=["date", "ts_code", "long_margin_rate_decimal", "short_margin_rate_decimal", "known_at", "unit_rule_id"])
    margin = LaggedMarginTable(empty_margin, sorted(data.mapping.date.unique()), 5)
    return settings, data, cal, signals, fees, margin


class IntegrationTests(unittest.TestCase):
    def test_full_engine_future_prefix_invariance(self):
        settings, data, cal, signals, fees, margin = setup()
        cutoff = pd.Timestamp("2015-10-07")
        short = deepcopy(data)
        for name in ["bars", "mapping", "multiple_prices", "adjusted_prices"]:
            frame = getattr(short, name)
            setattr(short, name, frame.loc[frame.date.le(cutoff)].copy())
        ss, sd, sc, short_signals, sf, sm = setup(short)
        scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", "normal")
        short_result = BacktestEngineV62(ss, sd, short_signals["reference"], sf, sc).run_v62(scenario, sm)
        full_result = BacktestEngineV62(settings, data, signals["reference"], fees, cal).run_v62(scenario, margin)
        for attr in ["orders", "fills", "positions", "targets", "daily_equity", "pnl_by_instrument"]:
            actual = getattr(full_result, "equity" if attr == "daily_equity" else attr)
            expected = getattr(short_result, "equity" if attr == "daily_equity" else attr)
            date_column = "created_date" if attr == "orders" else "date"
            pd.testing.assert_frame_equal(expected.reset_index(drop=True), actual.loc[pd.to_datetime(actual[date_column]).le(cutoff)].reset_index(drop=True), atol=1e-7, rtol=0)

    def test_sleeve_netting_determinism_and_accounting(self):
        settings, data, cal, signals, fees, margin = setup()
        components = {"single_20_skip5": signals["single_20_skip5"], "single_250": signals["single_250"]}
        scenario = ScenarioV62("X", "sleeve_20skip5_250_equal_risk", "vendor_open", "static_fallback", "normal")
        engines = [SleeveEngineV62(settings, data, components, fees, cal), SleeveEngineV62(settings, data, components, fees, cal)]
        results = [engine.run_v62(scenario, margin) for engine in engines]
        for attr in ["equity", "orders", "fills", "positions", "targets", "pnl_by_instrument"]:
            pd.testing.assert_frame_equal(getattr(results[0], attr), getattr(results[1], attr), atol=1e-9, rtol=0)
        pd.testing.assert_frame_equal(pd.DataFrame(engines[0].internal_target_rows), pd.DataFrame(engines[1].internal_target_rows))
        self.assertLess(abs(results[0].equity.net_pnl.sum() - results[0].pnl_by_instrument.net_pnl.sum()), .01)
        fills = results[0].fills
        self.assertAlmostEqual(float(fills.cash_slippage_cost.sum()), float(fills.slippage_cost.sum()))
        self.assertTrue((fills.embedded_slippage_cost == 0).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
