from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from .costs_v3 import FeeSchedule
from .engine import BacktestEngine, BacktestResult, buffered_position


@dataclass(frozen=True)
class BacktestScenarioV3:
    label: str
    stage: str
    annual_vol_target: float = 0.275
    unfilled_mode: str = "cancel_recalculate"
    fee_multiplier: float = 1.5
    slippage_model: str = "normal"  # fixed / normal / stress
    fixed_slippage_ticks: float = 2.0
    rebalance_mode: str = "hybrid"  # daily / weekly / hybrid
    buffer_fraction: float = 0.10
    emergency_vol_ratio: float = 1.20

    @property
    def name(self) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.label)
        return f"{self.stage}__{safe}"

    @property
    def slippage_ticks(self) -> float:
        """Compatibility with the v2 analytics table."""
        return self.fixed_slippage_ticks if self.slippage_model == "fixed" else np.nan


@dataclass
class PendingOrderV3:
    contract: str
    instrument: str
    quantity: int
    created_date: pd.Timestamp
    reason: str
    attempts: int = 0


class BacktestEngineV3(BacktestEngine):
    def __init__(self, settings, data, signals, fee_schedule: FeeSchedule):
        super().__init__(settings, data, signals)
        self.fee_schedule = fee_schedule
        signal_dates = pd.to_datetime(signals.selections.get("signal_date", pd.Series(dtype="datetime64[ns]")))
        self.weekly_signal_dates = set(signal_dates.dropna().unique())

    def run(self, scenario: BacktestScenarioV3) -> BacktestResult:
        if scenario.unfilled_mode not in {"retry", "cancel_recalculate"}:
            raise ValueError(f"Unknown unfilled mode {scenario.unfilled_mode}")
        if scenario.rebalance_mode not in {"daily", "weekly", "hybrid"}:
            raise ValueError(f"Unknown rebalance mode {scenario.rebalance_mode}")
        run = self.settings.section("run")
        dates = pd.DatetimeIndex(sorted(self.data.mapping["date"].unique()))
        dates = dates[(dates >= pd.Timestamp(run["start"])) & (dates <= pd.Timestamp(run["end"]))]
        equity = float(run["initial_capital"])
        positions: dict[str, int] = {}
        lots: dict[str, list[dict[str, Any]]] = {}
        previous_marks: dict[str, float] = {}
        pending: dict[str, PendingOrderV3] = {}
        equity_rows: list[dict[str, Any]] = []
        position_rows: list[dict[str, Any]] = []
        target_rows: list[dict[str, Any]] = []
        order_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        rejection_rows: list[dict[str, Any]] = []
        pnl_rows: list[dict[str, Any]] = []
        portfolio_returns: list[float] = []
        counters: dict[str, int] = {
            "stale_mark_events": 0, "commodity_margin_scaling_events": 0,
            "total_margin_scaling_events": 0, "commodity_leverage_scaling_events": 0,
            "covariance_scaling_days": 0, "realized_vol_feedback_days": 0,
            "buffer_evaluations": 0, "buffer_holds": 0, "buffer_trades": 0,
            "buffer_roll_bypasses": 0, "normal_rebalance_days": 0,
            "non_rebalance_days": 0, "emergency_vol_trigger_days": 0,
            "emergency_vol_reduction_days": 0, "forced_constraint_days": 0,
            "actual_total_margin_breach_days": 0, "actual_commodity_margin_breach_days": 0,
        }

        for date in dates:
            start_positions = positions.copy()
            day_fills: list[dict[str, Any]] = []
            residual: dict[str, PendingOrderV3] = {}
            for contract, order in list(pending.items()):
                order.attempts += 1
                fills, remainder, rejection = self._execute_order_v3(date, order, scenario, lots)
                for fill in fills:
                    positions[contract] = positions.get(contract, 0) + int(fill["quantity"])
                    if positions[contract] == 0:
                        positions.pop(contract, None)
                    day_fills.append(fill)
                    fill_rows.append(fill)
                if remainder:
                    residual[contract] = PendingOrderV3(
                        contract, order.instrument, remainder, order.created_date,
                        order.reason, order.attempts,
                    )
                if rejection is not None:
                    rejection_rows.append(rejection)
            pending = residual if scenario.unfilled_mode == "retry" else {}
            self._assert_lot_ledger(positions, lots)

            gross_pnl, fees, stale_today, day_pnl_rows = self._mark_to_market(
                date, start_positions, day_fills, previous_marks
            )
            pnl_rows.extend(day_pnl_rows)
            counters["stale_mark_events"] += stale_today
            equity_before_pnl = equity
            equity += gross_pnl - fees
            if equity <= 0:
                raise RuntimeError(f"Equity depleted on {date.date()}")
            portfolio_returns.append((gross_pnl - fees) / equity_before_pnl)

            optimal, sizing_diag = self._calculate_targets(
                date, equity, positions, scenario, portfolio_returns
            )
            counters["commodity_margin_scaling_events"] += int(sizing_diag["commodity_margin_scaled"])
            counters["total_margin_scaling_events"] += int(sizing_diag["total_margin_scaled"])
            counters["commodity_leverage_scaling_events"] += int(sizing_diag["commodity_leverage_scaled"])
            counters["covariance_scaling_days"] += int(sizing_diag["diversification_multiplier"] != 1.0)
            counters["realized_vol_feedback_days"] += int(sizing_diag["realized_vol_multiplier"] != 1.0)

            desired, schedule_diag, forced_reasons = self._scheduled_targets(
                date, optimal, positions, equity, sizing_diag, scenario
            )
            for key, value in schedule_diag.items():
                counters[key] += int(value)
            all_contracts = set(positions) | set(desired)
            if scenario.unfilled_mode == "retry":
                all_contracts -= set(pending)
            for contract in sorted(all_contracts):
                quantity = int(desired.get(contract, 0) - positions.get(contract, 0))
                if quantity == 0:
                    continue
                instrument = self._instrument_for_contract(contract)
                reason = self._order_reason_v3(
                    date, contract, instrument, positions, desired, forced_reasons
                )
                order = PendingOrderV3(contract, instrument, quantity, date, reason)
                pending[contract] = order
                order_rows.append({
                    "created_date": date, "contract": contract, "instrument": instrument,
                    "quantity": quantity, "reason": reason, "scenario": scenario.name,
                    "rebalance_mode": scenario.rebalance_mode,
                })
            for contract, quantity in desired.items():
                target_rows.append({
                    "date": date, "contract": contract,
                    "instrument": self._instrument_for_contract(contract),
                    "optimal_position": int(optimal.get(contract, 0)),
                    "buffered_target": int(quantity), "scenario": scenario.name,
                    "normal_rebalance_day": bool(schedule_diag["normal_rebalance_days"]),
                    "emergency_trigger": bool(schedule_diag["emergency_vol_trigger_days"]),
                })

            margin = self._margin_required(date, positions)
            commodity_positions, exempt_positions = self._split_exempt_positions(positions)
            commodity_margin = self._margin_required(date, commodity_positions)
            exempt_margin = self._margin_required(date, exempt_positions)
            gross_notional = self._gross_notional(date, positions)
            commodity_notional = self._gross_notional(date, commodity_positions)
            exempt_notional = self._gross_notional(date, exempt_positions)
            margin_utilization = margin / equity
            commodity_margin_utilization = commodity_margin / equity
            counters["actual_total_margin_breach_days"] += int(
                margin_utilization > float(self.portfolio["max_total_margin_utilization"])
            )
            counters["actual_commodity_margin_breach_days"] += int(
                commodity_margin_utilization > float(self.portfolio["max_commodity_margin_utilization"])
            )
            equity_rows.append({
                "date": date, "equity": equity, "gross_pnl": gross_pnl, "fees": fees,
                "net_pnl": gross_pnl - fees, "margin": margin,
                "margin_utilization": margin_utilization, "gross_notional": gross_notional,
                "gross_leverage": gross_notional / equity, "pending_orders": len(pending),
                "commodity_margin": commodity_margin,
                "commodity_margin_utilization": commodity_margin_utilization,
                "exempt_margin": exempt_margin,
                "commodity_gross_notional": commodity_notional,
                "commodity_gross_leverage": commodity_notional / equity,
                "exempt_gross_notional": exempt_notional,
                "exempt_gross_leverage": exempt_notional / equity,
                "exante_vol_before_scaling": sizing_diag["exante_vol_before_scaling"],
                "diversification_multiplier": sizing_diag["diversification_multiplier"],
                "trailing_realized_volatility": sizing_diag["trailing_realized_volatility"],
                "realized_vol_multiplier": sizing_diag["realized_vol_multiplier"],
                "scenario": scenario.name,
            })
            for contract, quantity in positions.items():
                position_rows.append({
                    "date": date, "contract": contract,
                    "instrument": self._instrument_for_contract(contract),
                    "position": quantity, "scenario": scenario.name,
                })
            self._update_previous_closes(date, previous_marks, set(positions) | set(start_positions))

        diagnostics = {
            "scenario": scenario.name, **counters, "ending_pending_orders": len(pending),
            "dates": len(dates), "fee_multiplier": scenario.fee_multiplier,
            "slippage_model": scenario.slippage_model,
            "rebalance_mode": scenario.rebalance_mode,
            "buffer_fraction": scenario.buffer_fraction,
            "emergency_vol_ratio": scenario.emergency_vol_ratio,
            "fee_proxy_fill_segments": sum(bool(row["fee_is_proxy"]) for row in fill_rows),
            "market_impact_fill_segments": sum(int(row["impact_ticks"] > 0) for row in fill_rows),
        }
        return BacktestResult(
            scenario=scenario, equity=pd.DataFrame(equity_rows),
            positions=pd.DataFrame(position_rows), targets=pd.DataFrame(target_rows),
            orders=pd.DataFrame(order_rows), fills=pd.DataFrame(fill_rows),
            rejections=pd.DataFrame(rejection_rows),
            pnl_by_instrument=pd.DataFrame(pnl_rows), diagnostics=diagnostics,
        )

    def _scheduled_targets(
        self, date: pd.Timestamp, optimal: dict[str, int], positions: dict[str, int],
        equity: float, sizing_diag: dict[str, Any], scenario: BacktestScenarioV3,
    ) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
        is_weekly = date in self.weekly_signal_dates
        normal_day = scenario.rebalance_mode == "daily" or is_weekly
        diagnostics = {
            "buffer_evaluations": 0, "buffer_holds": 0, "buffer_trades": 0,
            "buffer_roll_bypasses": 0, "normal_rebalance_days": int(normal_day),
            "non_rebalance_days": int(not normal_day), "emergency_vol_trigger_days": 0,
            "emergency_vol_reduction_days": 0, "forced_constraint_days": 0,
        }
        forced_reasons: dict[str, str] = {}
        if normal_day:
            desired, buffer_diag = self._apply_buffer_fraction(
                date, optimal, positions, scenario.buffer_fraction
            )
            for key, value in buffer_diag.items():
                diagnostics[f"buffer_{key}" if not key.startswith("buffer_") else key] = value
        else:
            desired = dict(positions)
            # Signal exits and rolls are never delayed to the weekly rebalance.
            for contract in list(positions):
                instrument = self._instrument_for_contract(contract)
                direction = int(self.directions.get((date, instrument), 0))
                mapped = self.mapping.get((date, instrument))
                if direction == 0:
                    desired.pop(contract, None)
                    forced_reasons[contract] = "signal_exit"
                elif mapped and mapped != contract:
                    desired.pop(contract, None)
                    forced_reasons[contract] = "roll"
                    if mapped in optimal:
                        desired[mapped] = optimal[mapped]
                        forced_reasons[mapped] = "roll"

            trailing = float(sizing_diag.get("trailing_realized_volatility", np.nan))
            if scenario.rebalance_mode == "hybrid" and np.isfinite(trailing):
                trigger = trailing > scenario.annual_vol_target * scenario.emergency_vol_ratio
                diagnostics["emergency_vol_trigger_days"] = int(trigger)
                if trigger:
                    changed = False
                    for contract, current in list(desired.items()):
                        target = int(optimal.get(contract, 0))
                        if target == 0 or np.sign(target) != np.sign(current):
                            desired.pop(contract, None)
                            forced_reasons[contract] = "volatility_forced"
                            changed = True
                        elif abs(target) < abs(current):
                            desired[contract] = target
                            forced_reasons[contract] = "volatility_forced"
                            changed = True
                    diagnostics["emergency_vol_reduction_days"] = int(changed)

        before_hard = dict(desired)
        hard_diag = self._scale_for_portfolio_constraints(date, desired, equity)
        forced_reduction = False
        for contract in set(before_hard) | set(desired):
            if before_hard.get(contract, 0) != desired.get(contract, 0):
                current = int(positions.get(contract, 0))
                after = int(desired.get(contract, 0))
                # Scaling a proposed increase is still a constrained normal
                # rebalance, not a forced liquidation. Label margin_forced only
                # when the executable target reduces an already-held exposure.
                if current and (after == 0 or (np.sign(after) == np.sign(current) and abs(after) < abs(current))):
                    forced_reasons[contract] = "margin_forced"
                    forced_reduction = True
        diagnostics["forced_constraint_days"] = int(forced_reduction)
        # Existing diagnostics count both pre-buffer sizing and executable hard checks.
        diagnostics["commodity_margin_scaling_events"] = int(hard_diag["commodity_margin_scaled"])
        diagnostics["total_margin_scaling_events"] = int(hard_diag["total_margin_scaled"])
        diagnostics["commodity_leverage_scaling_events"] = int(hard_diag["commodity_leverage_scaled"])
        return desired, diagnostics, forced_reasons

    def _mark_to_market(
        self, date: pd.Timestamp, start_positions: dict[str, int], fills: list[dict[str, Any]],
        previous_closes: dict[str, float],
    ) -> tuple[float, float, int, list[dict[str, Any]]]:
        pnl = 0.0
        stale = 0
        detail_rows: list[dict[str, Any]] = []
        contracts = set(start_positions) | {fill["contract"] for fill in fills}
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
            old_position = start_positions.get(contract, 0)
            previous = previous_closes.get(contract)
            contract_pnl = 0.0
            contract_fills = [item for item in fills if item["contract"] == contract]
            if old_position and previous is not None and np.isfinite(mark):
                contract_pnl += old_position * (mark - previous) * point_value
            for fill in contract_fills:
                contract_pnl += fill["quantity"] * (mark - fill["price"]) * point_value
            contract_fees = float(sum(fill["commission"] for fill in contract_fills))
            pnl += contract_pnl
            if contract_pnl or contract_fees:
                net_after_fill = old_position + sum(int(item["quantity"]) for item in contract_fills)
                direction = int(np.sign(old_position if old_position else net_after_fill))
                detail_rows.append({
                    "date": date, "contract": contract, "instrument": instrument,
                    "sector": self.sector_by_instrument.get(instrument, "unknown"),
                    "position_direction": direction, "gross_pnl": contract_pnl,
                    "commission": contract_fees, "net_pnl": contract_pnl - contract_fees,
                })
        fees = float(sum(fill["commission"] for fill in fills))
        return pnl, fees, stale, detail_rows

    def _apply_buffer_fraction(
        self, date: pd.Timestamp, optimal: dict[str, int], positions: dict[str, int], fraction: float
    ) -> tuple[dict[str, int], dict[str, int]]:
        desired: dict[str, int] = {}
        diagnostics = {"evaluations": 0, "holds": 0, "trades": 0, "roll_bypasses": 0}
        current_contract_by_instrument = {
            self._instrument_for_contract(contract): contract for contract in positions
        }
        for contract, target in optimal.items():
            instrument = self._instrument_for_contract(contract)
            if current_contract_by_instrument.get(instrument) not in {None, contract}:
                desired[contract] = target
                diagnostics["roll_bypasses"] += 1
                continue
            current = positions.get(contract, 0)
            buffered = buffered_position(current, target, fraction)
            desired[contract] = buffered
            diagnostics["evaluations"] += 1
            if current != target and buffered == current:
                diagnostics["holds"] += 1
            elif buffered != current:
                diagnostics["trades"] += 1
        return {key: value for key, value in desired.items() if value != 0}, diagnostics

    def _execute_order_v3(
        self, date: pd.Timestamp, order: PendingOrderV3, scenario: BacktestScenarioV3,
        lots: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
        key = (date, order.contract)
        if key not in self.bars.index:
            return [], order.quantity, self._rejection_v3(date, order, "missing_bar")
        bar = self.bars.loc[key]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[-1]
        if not np.isfinite(bar.get("open", np.nan)):
            return [], order.quantity, self._rejection_v3(date, order, "no_open")
        if self.execution.get("reject_locked_limit", True) and self._is_adverse_limit_at_open(bar, order.quantity):
            return [], order.quantity, self._rejection_v3(date, order, "adverse_limit_at_open")

        liquidity = self.liquidity.get((order.created_date, order.instrument), {})
        available_volume = float(liquidity.get("median_volume", np.nan))
        if not np.isfinite(available_volume) or available_volume <= 0:
            available_volume = float(self.execution.get("fallback_executable_volume", 10_000))
        maximum = max(0, int(math.floor(
            available_volume * float(self.execution["max_volume_participation"])
        )))
        fill_abs = min(abs(order.quantity), maximum)
        if fill_abs == 0:
            return [], order.quantity, self._rejection_v3(date, order, "lagged_participation_limit")
        total_fill_quantity = int(math.copysign(fill_abs, order.quantity))
        participation = fill_abs / available_volume
        impact_ticks = self._impact_ticks(participation)
        base_ticks, liquidity_tier = self._base_slippage_ticks(
            scenario, order.instrument, liquidity
        )
        roll_ticks = float(self.execution.get("roll_extra_ticks", 1.0)) if order.reason == "roll" else 0.0
        total_ticks = base_ticks + roll_ticks + impact_ticks
        tick_size = self._value(bar, "tick_size", self._fallback(order.instrument)[1])
        raw_fill_price = float(bar["open"]) + math.copysign(total_ticks * tick_size, total_fill_quantity)
        fill_price = self._adverse_grid_price(raw_fill_price, tick_size, total_fill_quantity)
        if np.isfinite(bar.get("upper_limit", np.nan)):
            fill_price = min(fill_price, float(bar["upper_limit"]))
        if np.isfinite(bar.get("lower_limit", np.nan)):
            fill_price = max(fill_price, float(bar["lower_limit"]))
        point_value = self._value(bar, "point_value", self._fallback(order.instrument)[0])
        segments = apply_trade_to_lot_ledger(
            lots.setdefault(order.contract, []), total_fill_quantity, pd.Timestamp(date)
        )
        fills: list[dict[str, Any]] = []
        for segment_index, (segment_quantity, trade_type) in enumerate(segments, start=1):
            charge = self.fee_schedule.charge(
                order.contract, order.instrument, date, trade_type,
                abs(segment_quantity), fill_price, point_value, scenario.fee_multiplier,
            )
            fills.append({
                "date": date, "created_date": order.created_date, "contract": order.contract,
                "instrument": order.instrument, "quantity": segment_quantity,
                "order_quantity": order.quantity, "segment_index": segment_index,
                "transaction_type": trade_type, "price": fill_price,
                "open_price": float(bar["open"]),
                "slippage_cost": abs(segment_quantity) * abs(fill_price - float(bar["open"])) * point_value,
                "base_slippage_ticks": base_ticks, "roll_extra_ticks": roll_ticks,
                "impact_ticks": impact_ticks, "total_slippage_ticks": total_ticks,
                "participation_rate": participation, "liquidity_tier": liquidity_tier,
                "lagged_median_volume": available_volume, "point_value": point_value,
                "traded_notional": abs(segment_quantity) * fill_price * point_value,
                "exchange_commission": charge.exchange_fee,
                "commission": charge.client_fee, "fee_multiplier": scenario.fee_multiplier,
                "fee_per_lot": charge.fee_per_lot, "fee_rate": charge.fee_rate,
                "fee_rule_id": charge.rule_id, "fee_source_type": charge.source_type,
                "fee_source_url": charge.source_url, "fee_is_proxy": charge.is_proxy,
                "attempt": order.attempts, "reason": order.reason,
                "scenario": scenario.name,
            })
        remainder = order.quantity - total_fill_quantity
        rejection = self._rejection_v3(date, order, "partial_fill", remainder) if remainder else None
        return fills, remainder, rejection

    def _base_slippage_ticks(
        self, scenario: BacktestScenarioV3, instrument: str, liquidity: dict[str, float]
    ) -> tuple[float, str]:
        if scenario.slippage_model == "fixed":
            return float(scenario.fixed_slippage_ticks), "fixed"
        high_names = set(self.execution.get("high_liquidity_instruments", ["T", "RB", "AL"]))
        volume_ok = float(liquidity.get("median_volume", 0.0)) >= float(
            self.execution.get("high_liquidity_min_median_volume", 10_000)
        )
        oi_ok = float(liquidity.get("median_open_interest", 0.0)) >= float(
            self.execution.get("high_liquidity_min_median_open_interest", 20_000)
        )
        high = instrument in high_names and volume_ok and oi_ok
        if scenario.slippage_model == "normal":
            return (1.0 if high else 2.0), ("核心高流动性" if high else "其他")
        if scenario.slippage_model == "stress":
            return (2.0 if high else 3.0), ("核心高流动性" if high else "其他")
        raise ValueError(f"Unknown slippage model {scenario.slippage_model}")

    @staticmethod
    def _impact_ticks(participation: float) -> float:
        if participation <= 0.01:
            return 0.0
        if participation <= 0.03:
            return 1.0
        return 2.0

    @staticmethod
    def _adverse_grid_price(price: float, tick_size: float, quantity: int) -> float:
        units = price / tick_size
        snapped = math.ceil(units - 1e-10) if quantity > 0 else math.floor(units + 1e-10)
        return float(round(snapped * tick_size, 10))

    @staticmethod
    def _is_adverse_limit_at_open(bar: pd.Series, quantity: int) -> bool:
        open_price = float(bar["open"])
        if quantity > 0 and np.isfinite(bar.get("upper_limit", np.nan)):
            return open_price >= float(bar["upper_limit"])
        if quantity < 0 and np.isfinite(bar.get("lower_limit", np.nan)):
            return open_price <= float(bar["lower_limit"])
        return False

    def _order_reason_v3(
        self, date: pd.Timestamp, contract: str, instrument: str,
        positions: dict[str, int], desired: dict[str, int], forced: dict[str, str],
    ) -> str:
        held_contracts = [item for item in positions if self._instrument_for_contract(item) == instrument]
        mapped = self.mapping.get((date, instrument))
        if held_contracts and mapped and any(item != mapped for item in held_contracts):
            return "roll"
        if contract in forced:
            return forced[contract]
        if desired.get(contract, 0) == 0 and int(self.directions.get((date, instrument), 0)) == 0:
            return "signal_exit"
        return "normal_rebalance"

    @staticmethod
    def _rejection_v3(
        date: pd.Timestamp, order: PendingOrderV3, reason: str, remainder: int | None = None
    ) -> dict[str, Any]:
        return {
            "date": date, "created_date": order.created_date, "contract": order.contract,
            "instrument": order.instrument,
            "quantity_remaining": order.quantity if remainder is None else remainder,
            "attempt": order.attempts, "reason": reason,
        }

    @staticmethod
    def _assert_lot_ledger(
        positions: dict[str, int], lots: dict[str, list[dict[str, Any]]]
    ) -> None:
        ledger = {
            contract: int(sum(int(item["quantity"]) for item in entries))
            for contract, entries in lots.items() if entries
        }
        ledger = {key: value for key, value in ledger.items() if value != 0}
        if ledger != positions:
            raise AssertionError(f"Lot ledger mismatch: {ledger} != {positions}")


def apply_trade_to_lot_ledger(
    lots: list[dict[str, Any]], quantity: int, date: pd.Timestamp
) -> list[tuple[int, str]]:
    """Apply a signed fill FIFO and split close/open across zero.

    Older lots are closed before same-day lots.  This makes the transaction
    type deterministic and gives a directly hand-checkable fee calculation.
    """
    if quantity == 0:
        return []
    date = pd.Timestamp(date)
    net = int(sum(int(item["quantity"]) for item in lots))
    if net == 0 or np.sign(net) == np.sign(quantity):
        lots.append({"open_date": date, "quantity": int(quantity)})
        return [(int(quantity), "open")]

    remaining = abs(int(quantity))
    order_sign = int(np.sign(quantity))
    segments: list[tuple[int, str]] = []
    # Oldest positions first; a same-day lot is only classified close_today if
    # all older inventory has already been closed.
    lots.sort(key=lambda item: pd.Timestamp(item["open_date"]))
    for lot in list(lots):
        if remaining == 0:
            break
        if int(lot["quantity"]) == 0 or np.sign(lot["quantity"]) == order_sign:
            continue
        close_abs = min(remaining, abs(int(lot["quantity"])))
        segment_quantity = order_sign * close_abs
        trade_type = (
            "close_today" if pd.Timestamp(lot["open_date"]).normalize() == date.normalize()
            else "close_non_today"
        )
        segments.append((segment_quantity, trade_type))
        lot["quantity"] = int(lot["quantity"]) + segment_quantity
        remaining -= close_abs
    lots[:] = [item for item in lots if int(item["quantity"]) != 0]
    if remaining:
        open_quantity = order_sign * remaining
        lots.append({"open_date": date, "quantity": open_quantity})
        segments.append((open_quantity, "open"))
    return segments
