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


@dataclass(frozen=True)
class ScenarioV61:
    scenario_id: str
    strategy: str
    one_price_policy: str
    slippage: str
    execution_proxy: str
    fee_semantics: str

    def cost(self) -> CostSpecV41:
        if self.slippage == "fixed_1_tick":
            return CostSpecV41("V61_FIXED1", 1.5, "fixed", 0, 1, 1, True)
        if self.slippage == "fixed_3_tick":
            return CostSpecV41("V61_FIXED3", 1.5, "fixed", 0, 3, 1, True)
        return CostSpecV41("V61_NORMAL", 1.5, "normal_shift", 0, 0, 1, True)

    def legacy_scenario(self) -> ScenarioV41:
        return ScenarioV41(self.scenario_id, self.scenario_id, self.cost())


def corrected_fee_schedule(legacy_rules: pd.DataFrame) -> FeeSchedule:
    """Correct only the documented proportional-unit defect; fixed fees stay fixed."""
    rules = legacy_rules.copy()
    rules["fee_rate"] = pd.to_numeric(rules["fee_rate"], errors="coerce").fillna(0.0) * 10.0
    rules["fee_rate_unit"] = "成交金额比例（Tushare原值/1000；v6.1修正）"
    rules["rule_id"] = rules["rule_id"].astype(str) + "-V61D1000"
    rules["source_type"] = rules["source_type"].astype(str) + "|V61_CORRECTED_RATE_UNIT"
    return FeeSchedule(rules)


class _ExecutionProxyMixin:
    v61_scenario: ScenarioV61

    def run_v61(self, scenario: ScenarioV61):
        self.v61_scenario = scenario
        self.one_price_order_events: list[dict[str, Any]] = []
        result = self.run_v4_2(scenario.legacy_scenario())
        result.scenario = scenario
        self._standardize_cost_columns(result)
        result.diagnostics.update({
            "research_status": "PROVISIONAL_DAILY_ONLY",
            "scenario_id": scenario.scenario_id,
            "one_price_policy": scenario.one_price_policy,
            "execution_proxy": scenario.execution_proxy,
            "fee_semantics": scenario.fee_semantics,
            "one_price_order_event_count": len(self.one_price_order_events),
        })
        return result

    @staticmethod
    def _standardize_cost_columns(result) -> None:
        fills = result.fills
        if "cash_slippage_cost" not in fills:
            fills["cash_slippage_cost"] = 0.0
        if "base_slippage_cost" not in fills:
            fills["base_slippage_cost"] = fills["base_slippage_ticks"] * fills["point_value"] * fills["quantity"].abs()
        if "roll_slippage_cost" not in fills:
            fills["roll_slippage_cost"] = fills["roll_extra_ticks"] * fills["point_value"] * fills["quantity"].abs()
        if "impact_cost" not in fills:
            fills["impact_cost"] = fills["impact_ticks"] * fills["point_value"] * fills["quantity"].abs()

    @staticmethod
    def _one_price(bar: pd.Series) -> bool:
        high, low = bar.get("high", np.nan), bar.get("low", np.nan)
        return bool(np.isfinite(high) and np.isfinite(low) and float(high) == float(low))

    def _proxy_rejection(self, date, order, bar) -> str | None:
        if not self._one_price(bar):
            return None
        policy = self.v61_scenario.one_price_policy
        if policy in {"legacy", "p0"}:
            return None
        if policy == "p2":
            return "DAILY_ONE_PRICE_ALL_SIDE_STRESS_REJECT"
        if policy != "p1":
            raise ValueError(f"Unknown one-price policy {policy}")
        price = float(bar["high"])
        pre = bar.get("pre_settle", np.nan)
        if not np.isfinite(pre) or float(bar.get("volume", 0.0)) <= 0 or price == float(pre):
            return "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT"
        adverse = (order.quantity > 0 and price > float(pre)) or (order.quantity < 0 and price < float(pre))
        return "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT" if adverse else None

    def _execute_order_v3(
        self, date: pd.Timestamp, order: PendingOrderV3, scenario, lots: dict[str, list[dict[str, Any]]]
    ):
        key = (date, order.contract)
        if key not in self.bars.index:
            return [], order.quantity, self._rejection_v3(date, order, "missing_bar")
        bar = self.bars.loc[key]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[-1]
        reference_field = "close" if self.v61_scenario.execution_proxy == "next_close" else "open"
        if not np.isfinite(bar.get(reference_field, np.nan)):
            return [], order.quantity, self._rejection_v3(date, order, f"no_{reference_field}")
        if float(bar.get("volume", 0.0)) <= 0:
            return [], order.quantity, self._rejection_v3(date, order, "DAILY_ZERO_VOLUME_PROXY_REJECT")
        proxy_reason = self._proxy_rejection(date, order, bar)
        if self._one_price(bar):
            self.one_price_order_events.append({
                "date": date, "created_date": order.created_date, "contract": order.contract,
                "instrument": order.instrument, "quantity": order.quantity,
                "one_price": float(bar["high"]), "pre_settle": bar.get("pre_settle", np.nan),
                "policy": self.v61_scenario.one_price_policy,
                "decision": "REJECT" if proxy_reason else "ALLOW",
                "reason_code": proxy_reason or "DAILY_ONE_PRICE_PROXY_ALLOWED",
                "scope": "ACTUAL_REAL_ORDER_OR_ROLL_LEG",
            })
        if proxy_reason:
            return [], order.quantity, self._rejection_v3(date, order, proxy_reason)

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
        tick = self._value(bar, "tick_size", self._fallback(order.instrument)[1])
        reference = float(bar[reference_field])
        if self.v61_scenario.execution_proxy == "next_close":
            fill_price = self._adverse_grid_price(reference, tick, total_quantity)
            cash_slippage = fill_abs * total_ticks * tick * self._value(bar, "point_value", self._fallback(order.instrument)[0])
        else:
            raw_price = reference + math.copysign(total_ticks * tick, total_quantity)
            fill_price = self._adverse_grid_price(raw_price, tick, total_quantity)
            low, high = bar.get("low", np.nan), bar.get("high", np.nan)
            if not np.isfinite(low) or not np.isfinite(high) or fill_price < float(low) or fill_price > float(high):
                return [], order.quantity, self._rejection_v3(date, order, "PROXY_SLIPPAGE_OUTSIDE_DAILY_RANGE")
            cash_slippage = 0.0
        point_value = self._value(bar, "point_value", self._fallback(order.instrument)[0])
        segments = apply_trade_to_lot_ledger(lots.setdefault(order.contract, []), total_quantity, pd.Timestamp(date))
        fills = []
        for index, (segment_quantity, trade_type) in enumerate(segments, start=1):
            charge = self.fee_schedule.charge(order.contract, order.instrument, date, trade_type, abs(segment_quantity), reference, point_value, scenario.fee_multiplier)
            segment_cash = cash_slippage * abs(segment_quantity) / fill_abs
            fills.append({
                "date": date, "created_date": order.created_date, "contract": order.contract,
                "instrument": order.instrument, "quantity": segment_quantity, "order_quantity": order.quantity,
                "segment_index": index, "transaction_type": trade_type, "price": fill_price,
                "reference_price": reference, "open_price": float(bar.get("open", np.nan)),
                "close_price": float(bar.get("close", np.nan)),
                "slippage_cost": abs(segment_quantity) * total_ticks * tick * point_value,
                "cash_slippage_cost": segment_cash,
                "base_slippage_ticks": base_ticks, "roll_extra_ticks": roll_ticks,
                "impact_ticks": impact_ticks, "total_slippage_ticks": total_ticks,
                "participation_rate": participation, "liquidity_tier": tier,
                "lagged_median_volume": available, "point_value": point_value,
                "traded_notional": abs(segment_quantity) * reference * point_value,
                "exchange_commission": charge.exchange_fee, "commission": charge.client_fee,
                "fee_multiplier": scenario.fee_multiplier, "fee_per_lot": charge.fee_per_lot,
                "fee_rate": charge.fee_rate, "fee_rule_id": charge.rule_id,
                "fee_source_type": charge.source_type, "fee_source_url": charge.source_url,
                "fee_is_proxy": charge.is_proxy, "attempt": order.attempts, "reason": order.reason,
                "scenario": self.v61_scenario.scenario_id, "execution_proxy": self.v61_scenario.execution_proxy,
            })
        remainder = order.quantity - total_quantity
        rejection = self._rejection_v3(date, order, "partial_fill", remainder) if remainder else None
        return fills, remainder, rejection

    def _mark_to_market(self, date, start_positions, fills, previous_marks):
        if self.v61_scenario.execution_proxy != "next_close":
            return super()._mark_to_market(date, start_positions, fills, previous_marks)
        gross = 0.0; total_cost = 0.0; stale = 0; details = []
        contracts = set(start_positions) | {x["contract"] for x in fills}
        for contract in contracts:
            key = (date, contract)
            if key not in self.bars.index:
                stale += 1; continue
            bar = self.bars.loc[key]
            if isinstance(bar, pd.DataFrame): bar = bar.iloc[-1]
            mark = self._mark_price(bar); instrument = self._instrument_for_contract(contract)
            pv = self._value(bar, "point_value", self._fallback(instrument)[0])
            old = start_positions.get(contract, 0); previous = previous_marks.get(contract)
            pnl = old * (mark - previous) * pv if old and previous is not None and np.isfinite(mark) else 0.0
            sub = [x for x in fills if x["contract"] == contract]
            # Closing segments realize at close; opening segments start earning next day.
            for fill in sub:
                if fill["transaction_type"] != "open":
                    pnl += fill["quantity"] * (mark - float(fill["reference_price"])) * pv
            commission = float(sum(x["commission"] for x in sub))
            cash = float(sum(x.get("cash_slippage_cost", 0.0) for x in sub))
            gross += pnl; total_cost += commission + cash
            if pnl or commission or cash:
                net_after = old + sum(int(x["quantity"]) for x in sub)
                details.append({"date": date, "contract": contract, "instrument": instrument,
                    "sector": self.sector_by_instrument.get(instrument, "unknown"),
                    "position_direction": int(np.sign(old if old else net_after)), "gross_pnl": pnl,
                    "commission": commission, "cash_slippage_cost": cash,
                    "net_pnl": pnl - commission - cash})
        return gross, total_cost, stale, details


class BacktestEngineV61(_ExecutionProxyMixin, BacktestEngineV42):
    pass


class SleeveEngineV61(_ExecutionProxyMixin, SleeveEngineV42):
    pass
