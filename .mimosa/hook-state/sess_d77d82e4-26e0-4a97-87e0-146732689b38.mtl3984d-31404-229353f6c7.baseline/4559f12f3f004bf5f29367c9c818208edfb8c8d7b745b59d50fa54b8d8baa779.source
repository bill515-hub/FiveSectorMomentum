from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .engine_v3 import BacktestEngineV3, BacktestScenarioV3
from .signals import SignalBundle


@dataclass(frozen=True)
class CostSpecV41:
    code: str = "C3"
    fee_multiplier: float = 1.5
    base_mode: str = "normal_shift"  # normal_shift/fixed/zero
    base_shift_ticks: int = 0
    fixed_ticks: int = 0
    roll_ticks: int = 1
    impact_enabled: bool = True


@dataclass(frozen=True)
class ScenarioV41:
    label: str
    stage: str
    cost: CostSpecV41 = CostSpecV41()

    @property
    def name(self) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.label)
        return f"{self.stage}__{safe}"

    def execution(self) -> BacktestScenarioV3:
        return BacktestScenarioV3(
            self.label, self.stage, annual_vol_target=.275,
            unfilled_mode="cancel_recalculate", fee_multiplier=self.cost.fee_multiplier,
            slippage_model="normal", fixed_slippage_ticks=float(self.cost.fixed_ticks),
            rebalance_mode="hybrid", buffer_fraction=.10, emergency_vol_ratio=1.20,
        )


COST_SPECS = {
    "C0": CostSpecV41("C0", 0.0, "zero", 0, 0, 0, False),
    "C1": CostSpecV41("C1", 1.5, "zero", 0, 0, 0, False),
    "C2": CostSpecV41("C2", 1.5, "normal_shift", -1, 0, 1, True),
    "C3": CostSpecV41("C3", 1.5, "normal_shift", 0, 0, 1, True),
    "C4": CostSpecV41("C4", 1.5, "normal_shift", 1, 0, 1, True),
    "C5": CostSpecV41("C5", 1.5, "normal_shift", 2, 0, 1, True),
    "C6": CostSpecV41("C6", 1.5, "fixed", 0, 2, 1, True),
    "C7": CostSpecV41("C7", 1.5, "fixed", 0, 3, 1, True),
}


class BacktestEngineV41(BacktestEngineV3):
    """Frozen v4 execution with registered component-wise cost switches."""

    def __init__(self, settings, data, signals, fee_schedule):
        if settings.raw.get("version") != "v4_1":
            raise ValueError("BacktestEngineV41 requires v4_1 settings")
        BacktestEngineV3.__init__(self, settings, data, signals, fee_schedule)
        self._cost = COST_SPECS["C3"]

    def run_v4_1(self, scenario: ScenarioV41):
        self._cost = scenario.cost
        self.execution = dict(self.settings.section("execution"))
        self.execution["roll_extra_ticks"] = float(scenario.cost.roll_ticks)
        result = BacktestEngineV3.run(self, scenario.execution())
        result.scenario = scenario
        return canonicalize_result(result)

    def _base_slippage_ticks(self, scenario, instrument, liquidity):
        if self._cost.base_mode == "zero":
            return 0.0, "zero"
        if self._cost.base_mode == "fixed":
            return float(self._cost.fixed_ticks), "fixed"
        high_names = set(self.execution.get("high_liquidity_instruments", ["T", "RB", "AL"]))
        volume_ok = float(liquidity.get("median_volume", 0.0)) >= float(self.execution["high_liquidity_min_median_volume"])
        oi_ok = float(liquidity.get("median_open_interest", 0.0)) >= float(self.execution["high_liquidity_min_median_open_interest"])
        base = 1 if instrument in high_names and volume_ok and oi_ok else 2
        tier = "核心高流动性" if base == 1 else "其他"
        return float(max(0, base + int(self._cost.base_shift_ticks))), tier

    def _impact_ticks(self, participation: float) -> float:
        return BacktestEngineV3._impact_ticks(participation) if self._cost.impact_enabled else 0.0


class SleeveEngineV41(BacktestEngineV41):
    def __init__(self, settings, data, signals_by_horizon, combined_signals, fee_schedule):
        super().__init__(settings, data, combined_signals, fee_schedule)
        self.signals_by_horizon = signals_by_horizon
        self.directions_by_horizon = {
            h: bundle.directions.set_index(["date", "instrument"])["direction"].to_dict()
            for h, bundle in signals_by_horizon.items()
        }
        self.internal_target_rows: list[dict] = []

    def run_v4_1(self, scenario: ScenarioV41):
        self.internal_target_rows = []
        return super().run_v4_1(scenario)

    def _calculate_targets(self, date, equity, positions, scenario, portfolio_returns):
        horizons = tuple(sorted(self.directions_by_horizon))
        annualizer = math.sqrt(float(self.volatility["annualization_days"]))
        raw_internal: list[dict] = []
        for horizon in horizons:
            active: dict[str, list[tuple[str, int]]] = {}
            directions = self.directions_by_horizon[horizon]
            for instrument, row in self.instrument_meta.iterrows():
                direction = int(directions.get((date, instrument), 0))
                if direction:
                    active.setdefault(row["sector"], []).append((instrument, direction))
            for sector, sector_weight in self.portfolio["sector_risk_weights"].items():
                legs = active.get(sector, [])
                allocated = equity * scenario.annual_vol_target * float(sector_weight) / len(horizons)
                if not legs:
                    self.internal_target_rows.append({
                        "date": date, "horizon": horizon, "sector": sector,
                        "instrument": None, "contract": None, "direction": 0,
                        "allocated_annual_risk": allocated, "internal_target": 0,
                        "internal_annual_risk": 0.0,
                        "unused_signal_share": True,
                    })
                    continue
                per_leg = allocated / len(legs)
                for instrument, direction in legs:
                    contract = self.mapping.get((date, instrument))
                    daily_vol = self.price_vol.get((date, instrument))
                    lots = 0
                    if contract and daily_vol is not None and np.isfinite(daily_vol) and daily_vol > 0:
                        point_value = self._contract_value(contract, "point_value", self._fallback(instrument)[0])
                        lots = int(math.floor(per_leg / (point_value * daily_vol * annualizer)))
                        liquidity = self.liquidity.get((date, instrument), {})
                        if np.isfinite(liquidity.get("median_volume", np.nan)):
                            lots = min(lots, int(math.floor(float(liquidity["median_volume"]) * float(self.portfolio["max_position_fraction_of_median_volume"]))))
                        if np.isfinite(liquidity.get("median_open_interest", np.nan)):
                            lots = min(lots, int(math.floor(float(liquidity["median_open_interest"]) * float(self.portfolio["max_position_fraction_of_median_open_interest"]))))
                    target = direction * lots
                    row = {
                        "date": date, "horizon": horizon, "sector": sector,
                        "instrument": instrument, "contract": contract, "direction": direction,
                        "allocated_annual_risk": per_leg, "internal_target": target,
                        "internal_annual_risk": abs(target) * point_value * daily_vol * annualizer if target else 0.0,
                        "unused_signal_share": target == 0,
                    }
                    self.internal_target_rows.append(row)
                    raw_internal.append(row)
        targets: dict[str, int] = {}
        for row in raw_internal:
            if row["contract"] and row["internal_target"]:
                targets[row["contract"]] = targets.get(row["contract"], 0) + int(row["internal_target"])
        targets = {k: v for k, v in targets.items() if v}
        self._cap_final_liquidity(date, targets)
        exante, diversification = self._scale_to_exante_volatility(date, targets, equity, scenario.annual_vol_target)
        trailing, realized = self._scale_by_realized_volatility(targets, portfolio_returns, scenario.annual_vol_target)
        constraints = self._scale_for_portfolio_constraints(date, targets, equity)
        return targets, {
            **constraints, "exante_vol_before_scaling": exante,
            "diversification_multiplier": diversification,
            "trailing_realized_volatility": trailing, "realized_vol_multiplier": realized,
        }

    def _scheduled_targets(self, date, optimal, positions, equity, sizing_diag, scenario):
        """Use the true net optimal target for non-weekly exit/roll decisions.

        A vote-count direction can be zero while unequal internal lots leave a
        non-zero contract target.  The inherited scheduler only needs a zero vs
        non-zero direction flag, so temporarily expose the net target state.
        """
        saved={}
        for instrument in self.instrument_meta.index:
            key=(date,instrument); saved[key]=self.directions.get(key,None)
            contract=self.mapping.get(key); target=int(optimal.get(contract,0)) if contract else 0
            self.directions[key]=int(np.sign(target))
        try:
            return super()._scheduled_targets(date,optimal,positions,equity,sizing_diag,scenario)
        finally:
            for key,value in saved.items():
                if value is None: self.directions.pop(key,None)
                else: self.directions[key]=value

    def _cap_final_liquidity(self, date, targets):
        for contract in list(targets):
            instrument = self._instrument_for_contract(contract)
            liquidity = self.liquidity.get((date, instrument), {})
            caps = []
            if np.isfinite(liquidity.get("median_volume", np.nan)):
                caps.append(int(math.floor(liquidity["median_volume"] * float(self.portfolio["max_position_fraction_of_median_volume"]))))
            if np.isfinite(liquidity.get("median_open_interest", np.nan)):
                caps.append(int(math.floor(liquidity["median_open_interest"] * float(self.portfolio["max_position_fraction_of_median_open_interest"]))))
            if caps:
                targets[contract] = int(np.sign(targets[contract]) * min(abs(targets[contract]), min(caps)))
            if not targets[contract]:
                targets.pop(contract)


def combined_sleeve_signal(signals_by_horizon: dict[int, SignalBundle]) -> SignalBundle:
    first = signals_by_horizon[sorted(signals_by_horizon)[0]]
    direction_frames = []
    score_frames = []
    selections = []
    for horizon, bundle in sorted(signals_by_horizon.items()):
        direction_frames.append(bundle.directions.set_index(["date", "instrument"])["direction"].rename(horizon))
        score_frames.append(bundle.scores.set_index(["date", "instrument"])["score"].rename(horizon))
        selections.append(bundle.selections.assign(horizon=horizon))
    directions = pd.concat(direction_frames, axis=1).sum(axis=1).apply(np.sign).astype(int).rename("direction").reset_index()
    meta = first.directions[["instrument", "sector"]].drop_duplicates()
    directions = directions.merge(meta, on="instrument", how="left")
    signal_dates = first.directions[["date", "signal_date"]].drop_duplicates("date")
    directions = directions.merge(signal_dates, on="date", how="left")[["date", "signal_date", "instrument", "sector", "direction"]]
    scores = pd.concat(score_frames, axis=1).mean(axis=1).rename("score").reset_index()
    return SignalBundle(
        scores=scores, daily_price_vol=first.daily_price_vol,
        eligibility=first.eligibility, liquidity=first.liquidity,
        selections=pd.concat(selections, ignore_index=True), directions=directions,
        diagnostics={"method": "strategy_sleeve_equal_fixed_sector_risk", "horizons": sorted(signals_by_horizon)},
    )


def canonicalize_result(result):
    keys = {
        "equity": ["date"], "positions": ["date", "contract", "instrument"],
        "targets": ["date", "contract", "instrument"],
        "orders": ["created_date", "contract", "instrument", "quantity", "reason"],
        "fills": ["date", "created_date", "contract", "instrument", "attempt", "transaction_type"],
        "rejections": ["date", "created_date", "contract", "instrument", "reason"],
        "pnl_by_instrument": ["date", "contract", "instrument"],
    }
    for attr, desired in keys.items():
        frame = getattr(result, attr)
        usable = [key for key in desired if key in frame]
        if usable and not frame.empty:
            setattr(result, attr, frame.sort_values(usable, kind="stable").reset_index(drop=True))
    return result
