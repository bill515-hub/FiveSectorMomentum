from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.engine_v3 import PendingOrderV3, apply_trade_to_lot_ledger
from five_sector_momentum.engine_v4_1 import CostSpecV41, ScenarioV41
from five_sector_momentum.engine_v4_2 import BacktestEngineV42, SleeveEngineV42
from five_sector_momentum.v6_1.engine import corrected_fee_schedule

from .margin import FALLBACK_SOURCE, LaggedMarginTable


@dataclass(frozen=True)
class ScenarioV62:
    scenario_id: str
    strategy: str
    execution_proxy: str
    margin_mode: str
    slippage: str

    def cost(self) -> CostSpecV41:
        if self.slippage == "fixed_1_tick":
            return CostSpecV41("V62_FIXED1", 1.5, "fixed", 0, 1, 1, True)
        if self.slippage == "fixed_3_tick":
            return CostSpecV41("V62_FIXED3", 1.5, "fixed", 0, 3, 1, True)
        return CostSpecV41("V62_NORMAL", 1.5, "normal_shift", 0, 0, 1, True)

    def legacy_scenario(self) -> ScenarioV41:
        return ScenarioV41(self.scenario_id, self.scenario_id, self.cost())


class _CausalExecutionMixin:
    v62_scenario: ScenarioV62

    def run_v62(self, scenario: ScenarioV62, margin_table: LaggedMarginTable):
        self.v62_scenario = scenario
        self.margin_table = margin_table
        self._margin_usage: dict[tuple, dict[str, Any]] = {}
        self.margin_constraint_rows: list[dict[str, Any]] = []
        result = self.run_v4_2(scenario.legacy_scenario())
        result.scenario = scenario
        result.diagnostics.update({
            "research_status": "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION",
            "scenario_id": scenario.scenario_id,
            "execution_proxy": scenario.execution_proxy,
            "margin_mode": scenario.margin_mode,
            "same_day_range_filter": False,
            "slippage_accounting": "CASH_ONCE",
        })
        fills = result.fills
        if not fills.empty:
            abs_lots = fills["quantity"].abs()
            fills["base_slippage_cost"] = abs_lots * fills["base_slippage_ticks"] * fills["tick_size"] * fills["point_value"]
            fills["roll_slippage_cost"] = abs_lots * fills["roll_extra_ticks"] * fills["tick_size"] * fills["point_value"]
            fills["impact_cost"] = abs_lots * fills["impact_ticks"] * fills["tick_size"] * fills["point_value"]
        return result

    @staticmethod
    def _grid_reference(reference: float, tick_size: float) -> float:
        return float(round(round(reference / tick_size) * tick_size, 10))

    def _execute_order_v3(self, date: pd.Timestamp, order: PendingOrderV3, scenario, lots: dict[str, list[dict[str, Any]]]):
        key = (date, order.contract)
        if key not in self.bars.index:
            return [], order.quantity, self._rejection_v3(date, order, "missing_bar")
        bar = self.bars.loc[key]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[-1]
        reference_field = "close" if self.v62_scenario.execution_proxy == "next_close" else "open"
        reference = bar.get(reference_field, np.nan)
        if not np.isfinite(reference) or float(reference) <= 0:
            return [], order.quantity, self._rejection_v3(date, order, f"no_{reference_field}")

        # Execution capacity is known at order creation.  No execution-day
        # high/low/close/settlement/final volume/final OI enters this decision.
        liquidity = self.liquidity.get((order.created_date, order.instrument), {})
        available = float(liquidity.get("median_volume", np.nan))
        if not np.isfinite(available) or available <= 0:
            available = float(self.execution.get("fallback_executable_volume", 10_000))
        maximum = max(0, int(math.floor(available * float(self.execution["max_volume_participation"]))))
        fill_abs = min(abs(order.quantity), maximum)
        if fill_abs == 0:
            return [], order.quantity, self._rejection_v3(date, order, "lagged_participation_limit")
        total_quantity = int(math.copysign(fill_abs, order.quantity))
        participation = fill_abs / available
        impact_ticks = self._impact_ticks(participation)
        base_ticks, tier = self._base_slippage_ticks(scenario, order.instrument, liquidity)
        roll_ticks = float(self.execution.get("roll_extra_ticks", 1.0)) if order.reason == "roll" else 0.0
        total_ticks = base_ticks + roll_ticks + impact_ticks
        tick_size = self._value(bar, "tick_size", self._fallback(order.instrument)[1])
        point_value = self._value(bar, "point_value", self._fallback(order.instrument)[0])
        fill_price = self._grid_reference(float(reference), tick_size)
        cash_slippage = fill_abs * total_ticks * tick_size * point_value
        segments = apply_trade_to_lot_ledger(lots.setdefault(order.contract, []), total_quantity, pd.Timestamp(date))
        fills = []
        for segment_index, (segment_quantity, trade_type) in enumerate(segments, start=1):
            charge = self.fee_schedule.charge(order.contract, order.instrument, date, trade_type, abs(segment_quantity), fill_price, point_value, scenario.fee_multiplier)
            segment_cash = cash_slippage * abs(segment_quantity) / fill_abs
            fills.append({
                "date": date, "created_date": order.created_date, "contract": order.contract,
                "instrument": order.instrument, "quantity": segment_quantity,
                "order_quantity": order.quantity, "segment_index": segment_index,
                "transaction_type": trade_type, "price": fill_price,
                "reference_price": float(reference), "reference_field": reference_field,
                "slippage_cost": segment_cash, "cash_slippage_cost": segment_cash,
                "embedded_slippage_cost": 0.0, "base_slippage_ticks": base_ticks,
                "roll_extra_ticks": roll_ticks, "impact_ticks": impact_ticks,
                "total_slippage_ticks": total_ticks, "tick_size": tick_size,
                "participation_rate": participation, "liquidity_tier": tier,
                "lagged_median_volume": available, "point_value": point_value,
                "traded_notional": abs(segment_quantity) * fill_price * point_value,
                "exchange_commission": charge.exchange_fee, "commission": charge.client_fee,
                "fee_multiplier": scenario.fee_multiplier, "fee_per_lot": charge.fee_per_lot,
                "fee_rate": charge.fee_rate, "fee_rule_id": charge.rule_id,
                "fee_source_type": charge.source_type, "fee_source_url": charge.source_url,
                "fee_is_proxy": charge.is_proxy, "attempt": order.attempts,
                "reason": order.reason, "scenario": self.v62_scenario.scenario_id,
                "execution_proxy": self.v62_scenario.execution_proxy,
            })
        remainder = order.quantity - total_quantity
        rejection = self._rejection_v3(date, order, "partial_fill", remainder) if remainder else None
        return fills, remainder, rejection

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
            for fill in sub:
                if self.v62_scenario.execution_proxy == "vendor_open" or fill["transaction_type"] != "open":
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

    def _margin_required(self, date: pd.Timestamp, positions: dict[str, int]) -> float:
        if getattr(self, "v62_scenario", None) is None or self.v62_scenario.margin_mode == "static_fallback":
            return super()._margin_required(date, positions)
        total = 0.0
        for contract, quantity in positions.items():
            key = (date, contract)
            if key not in self.bars.index or not quantity:
                continue
            bar = self.bars.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            instrument = self._instrument_for_contract(contract)
            point_value = self._value(bar, "point_value", self._fallback(instrument)[0])
            fallback = float(self._fallback(instrument)[2])
            lookup = self.margin_table.lookup(date, contract, quantity, fallback)
            effective = lookup.effective_rate * float(self.portfolio["broker_margin_multiplier"])
            notional = abs(quantity) * self._mark_price(bar) * point_value
            total += notional * effective
            usage_key = (pd.Timestamp(date), contract, int(np.sign(quantity)), lookup.rate_date, lookup.source_code, lookup.vendor_binding)
            existing = self._margin_usage.get(usage_key)
            row = {
                "scenario_id": self.v62_scenario.scenario_id, "date": pd.Timestamp(date),
                "contract": contract, "instrument": instrument, "direction": int(np.sign(quantity)),
                "rate_trade_date": lookup.rate_date, "known_at": lookup.known_at,
                "stale_trading_days": lookup.stale_trading_days, "vendor_rate": lookup.vendor_rate,
                "fallback_rate": lookup.base_rate, "base_effective_rate": lookup.effective_rate,
                "customer_effective_rate": effective, "source_code": lookup.source_code,
                "unit_rule_id": lookup.unit_rule_id, "vendor_binding": lookup.vendor_binding,
                "call_count": 1, "maximum_abs_quantity_seen": abs(int(quantity)),
                "maximum_notional_seen": notional,
            }
            if existing is None:
                self._margin_usage[usage_key] = row
            else:
                existing["call_count"] += 1
                existing["maximum_abs_quantity_seen"] = max(existing["maximum_abs_quantity_seen"], abs(int(quantity)))
                existing["maximum_notional_seen"] = max(existing["maximum_notional_seen"], notional)
        return total

    def _scale_for_portfolio_constraints(self, date, targets, equity):
        before = dict(targets)
        diagnostics = super()._scale_for_portfolio_constraints(date, targets, equity)
        for contract in sorted(set(before) | set(targets)):
            if before.get(contract, 0) != targets.get(contract, 0):
                self.margin_constraint_rows.append({
                    "scenario_id": self.v62_scenario.scenario_id, "date": pd.Timestamp(date),
                    "contract": contract, "instrument": self._instrument_for_contract(contract),
                    "before_target": before.get(contract, 0), "after_target": targets.get(contract, 0),
                    "reason_code": "MARGIN_OR_LEVERAGE_TARGET_REDUCTION",
                    **diagnostics,
                })
        return diagnostics

    def margin_usage_frame(self) -> pd.DataFrame:
        return pd.DataFrame(list(self._margin_usage.values()))


class BacktestEngineV62(_CausalExecutionMixin, BacktestEngineV42):
    pass


class SleeveEngineV62(_CausalExecutionMixin, SleeveEngineV42):
    pass


__all__ = ["ScenarioV62", "BacktestEngineV62", "SleeveEngineV62", "corrected_fee_schedule"]
