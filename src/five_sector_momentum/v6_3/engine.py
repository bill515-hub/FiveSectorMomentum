from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from five_sector_momentum.engine_v3 import BacktestEngineV3
from five_sector_momentum.engine_v4_1 import CostSpecV41, SleeveEngineV41, combined_sleeve_signal
from five_sector_momentum.engine_v4_2 import BacktestEngineV42, SleeveEngineV42
from five_sector_momentum.v6_2.engine import _CausalExecutionMixin
from five_sector_momentum.v6_2.margin import LaggedMarginTable


WATERMARK = "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION"


@dataclass(frozen=True)
class ScenarioV63:
    scenario_id: str
    strategy: str
    execution_proxy: str
    margin_mode: str
    slippage: str

    def cost(self) -> CostSpecV41:
        if self.slippage == "fixed_1_tick":
            return CostSpecV41("V63_FIXED1", 1.5, "fixed", 0, 1, 1, True)
        if self.slippage == "fixed_3_tick":
            return CostSpecV41("V63_FIXED3", 1.5, "fixed", 0, 3, 1, True)
        return CostSpecV41("V63_NORMAL", 1.5, "normal_shift", 0, 0, 1, True)

    def legacy_scenario(self):
        from five_sector_momentum.engine_v4_1 import ScenarioV41
        return ScenarioV41(self.scenario_id, self.scenario_id, self.cost())


class _V63ExecutionMixin(_CausalExecutionMixin):
    """v6.2 causal fill path plus complete daily settlement for next-close."""

    def run_v63(self, scenario: ScenarioV63, margin_table: LaggedMarginTable):
        result = self.run_v62(scenario, margin_table)
        result.diagnostics.update({
            "research_status": WATERMARK,
            "next_close_complete_daily_settlement": scenario.execution_proxy == "next_close",
            "next_close_opening_segment_only": True,
        })
        return result

    def _mark_to_market(self, date, start_positions, fills, previous_marks):
        gross = 0.0
        total_cost = 0.0
        stale = 0
        details = []
        contracts = set(start_positions) | {x["contract"] for x in fills}
        for contract in contracts:
            key = (date, contract)
            if key not in self.bars.index:
                stale += 1
                continue
            bar = self.bars.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            mark = self._mark_price(bar)
            instrument = self._instrument_for_contract(contract)
            point_value = self._value(bar, "point_value", self._fallback(instrument)[0])
            old = start_positions.get(contract, 0)
            previous = previous_marks.get(contract)
            pnl = old * (mark - previous) * point_value if old and previous is not None and np.isfinite(mark) else 0.0
            sub = [x for x in fills if x["contract"] == contract]
            # All segments settle on the execution date.  For a closing segment
            # this combines with old-position MTM to give an exit at fill.  For
            # an opening segment it adds only q*(settlement-fill); no duplicate
            # term is introduced and cross-zero trades are already lot-segmented.
            for fill in sub:
                pnl += fill["quantity"] * (mark - float(fill["price"])) * point_value
            commission = float(sum(x["commission"] for x in sub))
            cash = float(sum(x["cash_slippage_cost"] for x in sub))
            gross += pnl
            total_cost += commission + cash
            if pnl or commission or cash:
                net_after = old + sum(int(x["quantity"]) for x in sub)
                details.append({
                    "date": date, "contract": contract, "instrument": instrument,
                    "sector": self.sector_by_instrument.get(instrument, "unknown"),
                    "position_direction": int(np.sign(old if old else net_after)),
                    "gross_pnl": pnl, "commission": commission,
                    "cash_slippage_cost": cash, "net_pnl": pnl - commission - cash,
                })
        return gross, total_cost, stale, details


class BacktestEngineV63(_V63ExecutionMixin, BacktestEngineV42):
    pass


class SleeveEngineV63(_V63ExecutionMixin, SleeveEngineV42):
    """Generalized fixed-risk sleeve; supports the registered 2 or 3 components."""

    def __init__(self, settings, data, signals_by_horizon, fee_schedule, calendar):
        if len(signals_by_horizon) not in {2, 3}:
            raise ValueError("v6.3 registers only two- or three-component sleeves")
        combined = combined_sleeve_signal(signals_by_horizon)
        BacktestEngineV42.__init__(self, settings, data, combined, fee_schedule, calendar)
        self.directions_by_horizon = {
            key: bundle.directions.set_index(["date", "instrument"]).direction.to_dict()
            for key, bundle in signals_by_horizon.items()
        }
        self.internal_target_rows: list[dict[str, Any]] = []
        self.net_target_rows: list[dict[str, Any]] = []
        self.risk_rows: list[dict[str, Any]] = []

    def _calculate_targets(self, date, equity, positions, scenario, portfolio_returns):
        annualizer = math.sqrt(float(self.volatility["annualization_days"]))
        fraction = 1.0 / len(self.directions_by_horizon)
        rows: list[dict[str, Any]] = []
        for horizon in sorted(self.directions_by_horizon):
            directions = self.directions_by_horizon[horizon]
            for sector, weight in self.portfolio["sector_risk_weights"].items():
                legs = [
                    (instrument, int(directions.get((date, instrument), 0)))
                    for instrument, row in self.instrument_meta.iterrows()
                    if row["sector"] == sector and directions.get((date, instrument), 0)
                ]
                budget = equity * scenario.annual_vol_target * float(weight) * fraction
                if not legs:
                    rows.append({
                        "date": date, "horizon": horizon, "sector": sector,
                        "instrument": None, "contract": None, "direction": 0,
                        "internal_target": 0, "allocated_annual_risk": budget,
                        "internal_annual_risk": 0.0, "unused_annual_risk": budget,
                        "risk_fraction": float(weight) * fraction, "equity": equity,
                    })
                    continue
                for instrument, direction in legs:
                    contract = self.mapping.get((date, instrument))
                    vol = self.price_vol.get((date, instrument), np.nan)
                    one_lot = 0.0
                    if contract and vol is not None and np.isfinite(vol) and vol > 0:
                        one_lot = self._contract_value(
                            contract, "point_value", self._fallback(instrument)[0]
                        ) * vol * annualizer
                    per_leg = budget / len(legs)
                    lots = int(math.floor(per_leg / one_lot)) if one_lot > 0 else 0
                    rows.append({
                        "date": date, "horizon": horizon, "sector": sector,
                        "instrument": instrument, "contract": contract,
                        "direction": direction, "internal_target": direction * lots,
                        "allocated_annual_risk": per_leg,
                        "internal_annual_risk": lots * one_lot,
                        "unused_annual_risk": per_leg - lots * one_lot,
                        "risk_fraction": float(weight) * fraction / len(legs),
                        "equity": equity,
                    })
        self.internal_target_rows.extend(rows)
        net: dict[str, int] = {}
        gross: dict[str, int] = {}
        for row in rows:
            contract = row["contract"]
            quantity = int(row["internal_target"])
            if contract:
                net[contract] = net.get(contract, 0) + quantity
                gross[contract] = gross.get(contract, 0) + abs(quantity)
        targets = {contract: quantity for contract, quantity in net.items() if quantity}
        SleeveEngineV41._cap_final_liquidity(self, date, targets)
        after_liquidity = targets.copy()
        exante, diversification = self._scale_to_exante_volatility(
            date, targets, equity, scenario.annual_vol_target
        )
        trailing, realized = self._scale_by_realized_volatility(
            targets, portfolio_returns, scenario.annual_vol_target
        )
        for contract in sorted(net):
            self.net_target_rows.append({
                "date": date, "contract": contract,
                "instrument": self._instrument_for_contract(contract),
                "internal_gross_lots": gross[contract], "raw_net_target": net[contract],
                "cancelled_internal_lots": gross[contract] - abs(net[contract]),
                "liquidity_capped_net": after_liquidity.get(contract, 0),
                "scaled_net_optimal": targets.get(contract, 0),
                "internal_order_fees": 0.0,
            })
        self.risk_rows.append({
            "date": date, "equity": equity,
            "nominal_annual_risk": equity * scenario.annual_vol_target,
            "component_count": len(self.directions_by_horizon),
            "component_fraction": fraction,
            "exante_vol_before_scaling": exante,
            "diversification_multiplier": diversification,
            "trailing_realized_volatility": trailing,
            "realized_vol_multiplier": realized,
        })
        return targets, {
            "commodity_margin_scaled": False, "total_margin_scaled": False,
            "commodity_leverage_scaled": False,
            "exante_vol_before_scaling": exante,
            "diversification_multiplier": diversification,
            "trailing_realized_volatility": trailing,
            "realized_vol_multiplier": realized,
        }

    def _scheduled_targets(self, date, optimal, positions, equity, sizing_diag, scenario):
        saved = {}
        for instrument in self.instrument_meta.index:
            key = (date, instrument)
            saved[key] = self.directions.get(key)
            target = int(optimal.get(self.mapping.get(key), 0))
            self.directions[key] = int(np.sign(target))
        try:
            return BacktestEngineV3._scheduled_targets(
                self, date, optimal, positions, equity, sizing_diag, scenario
            )
        finally:
            for key, value in saved.items():
                if value is None:
                    self.directions.pop(key, None)
                else:
                    self.directions[key] = value


__all__ = ["ScenarioV63", "BacktestEngineV63", "SleeveEngineV63", "WATERMARK"]
