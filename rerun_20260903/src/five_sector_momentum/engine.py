from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from .data_pipeline import DataBundle
from .settings import Settings
from .signals import SignalBundle


@dataclass(frozen=True)
class BacktestScenario:
    annual_vol_target: float
    unfilled_mode: str
    slippage_ticks: float

    @property
    def name(self) -> str:
        vol = str(self.annual_vol_target).replace(".", "p")
        slip = str(self.slippage_ticks).replace(".", "p")
        return f"vol_{vol}__{self.unfilled_mode}__slip_{slip}t"


@dataclass
class BacktestResult:
    scenario: BacktestScenario
    equity: pd.DataFrame
    positions: pd.DataFrame
    targets: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    rejections: pd.DataFrame
    pnl_by_instrument: pd.DataFrame
    diagnostics: dict[str, Any]


@dataclass
class PendingOrder:
    contract: str
    instrument: str
    quantity: int
    created_date: pd.Timestamp
    reason: str
    attempts: int = 0


class BacktestEngine:
    def __init__(self, settings: Settings, data: DataBundle, signals: SignalBundle):
        self.settings = settings
        self.data = data
        self.signals = signals
        self.execution = settings.section("execution")
        self.portfolio = settings.section("portfolio")
        self.volatility = settings.section("volatility")
        self.bars = data.bars.set_index(["date", "ts_code"]).sort_index()
        self.mapping = data.mapping.set_index(["date", "instrument"])["contract"].to_dict()
        self.directions = signals.directions.set_index(["date", "instrument"])["direction"].to_dict()
        self.price_vol = signals.daily_price_vol.set_index(["date", "instrument"])["daily_price_vol"].to_dict()
        self.liquidity = signals.liquidity.set_index(["date", "instrument"])[
            ["median_volume", "median_open_interest"]
        ].to_dict("index")
        self.instrument_meta = data.instrument_meta.set_index("instrument")
        self.sector_by_instrument = self.instrument_meta["sector"].to_dict()
        self.leverage_exempt_sectors = set(
            self.portfolio.get("leverage_exempt_sectors", ["government_bond"])
        )
        self.contract_meta = data.contract_meta.set_index("ts_code")
        self.price_changes = (
            data.adjusted_prices.pivot(index="date", columns="instrument", values="adjusted_price")
            .sort_index().diff()
        )

    def run(self, scenario: BacktestScenario) -> BacktestResult:
        if scenario.unfilled_mode not in {"retry", "cancel_recalculate"}:
            raise ValueError(f"Unknown unfilled mode {scenario.unfilled_mode}")
        run = self.settings.section("run")
        dates = pd.DatetimeIndex(sorted(self.data.mapping["date"].unique()))
        dates = dates[(dates >= pd.Timestamp(run["start"])) & (dates <= pd.Timestamp(run["end"]))]
        equity = float(run["initial_capital"])
        positions: dict[str, int] = {}
        previous_closes: dict[str, float] = {}
        pending: dict[str, PendingOrder] = {}
        equity_rows: list[dict[str, Any]] = []
        position_rows: list[dict[str, Any]] = []
        target_rows: list[dict[str, Any]] = []
        order_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        rejection_rows: list[dict[str, Any]] = []
        pnl_rows: list[dict[str, Any]] = []
        stale_marks = 0
        commodity_margin_scalings = 0
        total_margin_scalings = 0
        commodity_leverage_scalings = 0
        covariance_scalings = 0
        buffer_evaluations = 0
        buffer_holds = 0
        buffer_trades = 0
        buffer_roll_bypasses = 0
        realized_vol_feedback_days = 0
        portfolio_returns: list[float] = []

        for date in dates:
            start_positions = positions.copy()
            day_fills: list[dict[str, Any]] = []
            residual: dict[str, PendingOrder] = {}
            for contract, order in list(pending.items()):
                order.attempts += 1
                filled, remainder, rejection = self._execute_order(date, order, scenario)
                if filled is not None:
                    positions[contract] = positions.get(contract, 0) + int(filled["quantity"])
                    if positions[contract] == 0:
                        positions.pop(contract, None)
                    day_fills.append(filled)
                    fill_rows.append(filled)
                if remainder:
                    residual[contract] = PendingOrder(
                        contract, order.instrument, remainder, order.created_date,
                        order.reason, order.attempts,
                    )
                if rejection is not None:
                    rejection_rows.append(rejection)
            pending = residual if scenario.unfilled_mode == "retry" else {}

            gross_pnl, fees, stale_today, day_pnl_rows = self._mark_to_market(
                date, start_positions, day_fills, previous_closes
            )
            pnl_rows.extend(day_pnl_rows)
            stale_marks += stale_today
            equity_before_pnl = equity
            equity += gross_pnl - fees
            if equity <= 0:
                raise RuntimeError(f"Equity depleted on {date.date()}")
            portfolio_returns.append((gross_pnl - fees) / equity_before_pnl)

            optimal, sizing_diag = self._calculate_targets(
                date, equity, positions, scenario, portfolio_returns
            )
            commodity_margin_scalings += int(sizing_diag["commodity_margin_scaled"])
            total_margin_scalings += int(sizing_diag["total_margin_scaled"])
            commodity_leverage_scalings += int(sizing_diag["commodity_leverage_scaled"])
            covariance_scalings += int(sizing_diag["diversification_multiplier"] != 1.0)
            realized_vol_feedback_days += int(sizing_diag["realized_vol_multiplier"] != 1.0)
            desired, buffer_diag = self._apply_position_buffers(date, optimal, positions)
            buffer_evaluations += buffer_diag["evaluations"]
            buffer_holds += buffer_diag["holds"]
            buffer_trades += buffer_diag["trades"]
            buffer_roll_bypasses += buffer_diag["roll_bypasses"]
            # A buffered current position can sit above a newly reduced constraint;
            # enforce hard portfolio limits again on the executable target.
            hard_diag = self._scale_for_portfolio_constraints(date, desired, equity)
            commodity_margin_scalings += int(hard_diag["commodity_margin_scaled"])
            total_margin_scalings += int(hard_diag["total_margin_scaled"])
            commodity_leverage_scalings += int(hard_diag["commodity_leverage_scaled"])
            all_contracts = set(positions) | set(desired)
            if scenario.unfilled_mode == "retry":
                all_contracts -= set(pending)
            for contract in sorted(all_contracts):
                quantity = int(desired.get(contract, 0) - positions.get(contract, 0))
                if quantity == 0:
                    continue
                instrument = self._instrument_for_contract(contract)
                reason = self._order_reason(date, contract, instrument, positions)
                order = PendingOrder(contract, instrument, quantity, date, reason)
                pending[contract] = order
                order_rows.append(
                    {"created_date": date, "contract": contract, "instrument": instrument,
                     "quantity": quantity, "reason": reason, "scenario": scenario.name}
                )
            for contract, quantity in desired.items():
                target_rows.append(
                    {"date": date, "contract": contract, "instrument": self._instrument_for_contract(contract),
                     "optimal_position": int(optimal.get(contract, 0)), "buffered_target": int(quantity),
                     "scenario": scenario.name}
                )

            margin = self._margin_required(date, positions)
            commodity_positions, exempt_positions = self._split_exempt_positions(positions)
            commodity_margin = self._margin_required(date, commodity_positions)
            exempt_margin = self._margin_required(date, exempt_positions)
            gross_notional = self._gross_notional(date, positions)
            commodity_notional = self._gross_notional(date, commodity_positions)
            exempt_notional = self._gross_notional(date, exempt_positions)
            equity_rows.append(
                {"date": date, "equity": equity, "gross_pnl": gross_pnl, "fees": fees,
                 "net_pnl": gross_pnl - fees, "margin": margin,
                 "margin_utilization": margin / equity, "gross_notional": gross_notional,
                 "gross_leverage": gross_notional / equity, "pending_orders": len(pending),
                 "commodity_margin": commodity_margin,
                 "commodity_margin_utilization": commodity_margin / equity,
                 "exempt_margin": exempt_margin,
                 "commodity_gross_notional": commodity_notional,
                 "commodity_gross_leverage": commodity_notional / equity,
                 "exempt_gross_notional": exempt_notional,
                 "exempt_gross_leverage": exempt_notional / equity,
                 "exante_vol_before_scaling": sizing_diag["exante_vol_before_scaling"],
                 "diversification_multiplier": sizing_diag["diversification_multiplier"],
                 "trailing_realized_volatility": sizing_diag["trailing_realized_volatility"],
                 "realized_vol_multiplier": sizing_diag["realized_vol_multiplier"],
                 "scenario": scenario.name}
            )
            for contract, quantity in positions.items():
                position_rows.append(
                    {"date": date, "contract": contract, "instrument": self._instrument_for_contract(contract),
                     "position": quantity, "scenario": scenario.name}
                )
            self._update_previous_closes(date, previous_closes, set(positions) | set(start_positions))

        diagnostics = {
            "scenario": scenario.name,
            "stale_mark_events": stale_marks,
            "commodity_margin_scaling_events": commodity_margin_scalings,
            "total_margin_scaling_events": total_margin_scalings,
            "commodity_leverage_scaling_events": commodity_leverage_scalings,
            "covariance_scaling_days": covariance_scalings,
            "realized_vol_feedback_days": realized_vol_feedback_days,
            "buffer_evaluations": buffer_evaluations,
            "buffer_holds": buffer_holds,
            "buffer_trades": buffer_trades,
            "buffer_roll_bypasses": buffer_roll_bypasses,
            "ending_pending_orders": len(pending),
            "dates": len(dates),
        }
        return BacktestResult(
            scenario=scenario,
            equity=pd.DataFrame(equity_rows),
            positions=pd.DataFrame(position_rows),
            targets=pd.DataFrame(target_rows),
            orders=pd.DataFrame(order_rows),
            fills=pd.DataFrame(fill_rows),
            rejections=pd.DataFrame(rejection_rows),
            pnl_by_instrument=pd.DataFrame(pnl_rows),
            diagnostics=diagnostics,
        )

    def _execute_order(
        self, date: pd.Timestamp, order: PendingOrder, scenario: BacktestScenario
    ) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
        key = (date, order.contract)
        if key not in self.bars.index:
            return None, order.quantity, self._rejection(date, order, "missing_bar")
        bar = self.bars.loc[key]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[-1]
        if not np.isfinite(bar.get("open", np.nan)) or bar.get("volume", 0) <= 0:
            return None, order.quantity, self._rejection(date, order, "no_open_or_volume")
        if self.execution.get("reject_locked_limit", True) and self._is_adverse_limit_lock(bar, order.quantity):
            return None, order.quantity, self._rejection(date, order, "adverse_limit_lock")
        maximum = max(0, int(math.floor(float(bar.get("volume", 0)) * float(self.execution["max_volume_participation"]))))
        fill_abs = min(abs(order.quantity), maximum)
        if fill_abs == 0:
            return None, order.quantity, self._rejection(date, order, "participation_limit")
        fill_quantity = int(math.copysign(fill_abs, order.quantity))
        tick_size = self._value(bar, "tick_size", self._fallback(order.instrument)[1])
        fill_price = float(bar["open"]) + math.copysign(scenario.slippage_ticks * tick_size, fill_quantity)
        if np.isfinite(bar.get("upper_limit", np.nan)):
            fill_price = min(fill_price, float(bar["upper_limit"]))
        if np.isfinite(bar.get("lower_limit", np.nan)):
            fill_price = max(fill_price, float(bar["lower_limit"]))
        point_value = self._value(bar, "point_value", self._fallback(order.instrument)[0])
        commission = self._commission(bar, fill_quantity, fill_price, point_value)
        fill = {
            "date": date, "created_date": order.created_date, "contract": order.contract,
            "instrument": order.instrument, "quantity": fill_quantity, "price": fill_price,
            "open_price": float(bar["open"]), "slippage_cost": abs(fill_quantity) * abs(fill_price - float(bar["open"])) * point_value,
            "point_value": point_value,
            "traded_notional": abs(fill_quantity) * fill_price * point_value,
            "commission": commission, "attempt": order.attempts, "reason": order.reason,
            "scenario": scenario.name,
        }
        remainder = order.quantity - fill_quantity
        rejection = self._rejection(date, order, "partial_fill", remainder) if remainder else None
        return fill, remainder, rejection

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
            point_value = self._value(bar, "point_value", self._fallback(self._instrument_for_contract(contract))[0])
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
                instrument = self._instrument_for_contract(contract)
                detail_rows.append(
                    {"date": date, "contract": contract, "instrument": instrument,
                     "sector": self.sector_by_instrument.get(instrument, "unknown"),
                     "gross_pnl": contract_pnl, "commission": contract_fees,
                     "net_pnl": contract_pnl - contract_fees}
                )
        fees = float(sum(fill["commission"] for fill in fills))
        return pnl, fees, stale, detail_rows

    def _calculate_targets(
        self, date: pd.Timestamp, equity: float, positions: dict[str, int],
        scenario: BacktestScenario, portfolio_returns: list[float],
    ) -> tuple[dict[str, int], dict[str, bool]]:
        active: dict[str, list[tuple[str, int]]] = {}
        for instrument, row in self.instrument_meta.iterrows():
            direction = int(self.directions.get((date, instrument), 0))
            if direction:
                active.setdefault(row["sector"], []).append((instrument, direction))
        targets: dict[str, int] = {}
        weights = self.portfolio["sector_risk_weights"]
        annualizer = math.sqrt(float(self.volatility["annualization_days"]))
        for sector, legs in active.items():
            per_leg_budget = equity * scenario.annual_vol_target * float(weights[sector]) / len(legs)
            for instrument, direction in legs:
                contract = self.mapping.get((date, instrument))
                daily_vol = self.price_vol.get((date, instrument))
                if not contract or daily_vol is None or not np.isfinite(daily_vol) or daily_vol <= 0:
                    continue
                point_value = self._contract_value(contract, "point_value", self._fallback(instrument)[0])
                one_lot_risk = point_value * daily_vol * annualizer
                lots = int(math.floor(per_leg_budget / one_lot_risk))
                liquidity = self.liquidity.get((date, instrument), {})
                volume_cap = float(self.portfolio["max_position_fraction_of_median_volume"])
                oi_cap = float(self.portfolio["max_position_fraction_of_median_open_interest"])
                median_volume = liquidity.get("median_volume", np.nan)
                median_oi = liquidity.get("median_open_interest", np.nan)
                if np.isfinite(median_volume):
                    lots = min(lots, int(math.floor(float(median_volume) * volume_cap)))
                if np.isfinite(median_oi):
                    lots = min(lots, int(math.floor(float(median_oi) * oi_cap)))
                if lots > 0:
                    targets[contract] = direction * lots
        exante_vol, diversification_multiplier = self._scale_to_exante_volatility(
            date, targets, equity, scenario.annual_vol_target
        )
        trailing_realized_vol, realized_vol_multiplier = self._scale_by_realized_volatility(
            targets, portfolio_returns, scenario.annual_vol_target
        )
        constraint_diag = self._scale_for_portfolio_constraints(date, targets, equity)
        return targets, {
            **constraint_diag,
            "exante_vol_before_scaling": exante_vol,
            "diversification_multiplier": diversification_multiplier,
            "trailing_realized_volatility": trailing_realized_vol,
            "realized_vol_multiplier": realized_vol_multiplier,
        }

    def _scale_by_realized_volatility(
        self, targets: dict[str, int], returns: list[float], target_vol: float
    ) -> tuple[float, float]:
        config = self.portfolio.get("realized_volatility_feedback", {})
        minimum = int(config.get("min_periods", 63))
        if not config.get("enabled", False) or len(returns) < minimum:
            return float("nan"), 1.0
        series = pd.Series(returns, dtype=float)
        trailing = float(
            series.ewm(
                span=int(config.get("ewma_span_days", 63)),
                min_periods=minimum, adjust=False,
            ).std(bias=False).iloc[-1] * math.sqrt(float(self.volatility["annualization_days"]))
        )
        if not np.isfinite(trailing) or trailing <= 0:
            return float("nan"), 1.0
        multiplier = float(np.clip(
            target_vol / trailing,
            float(config.get("minimum_multiplier", 0.75)),
            float(config.get("maximum_multiplier", 1.35)),
        ))
        self._scale_integer_targets(targets, multiplier)
        return trailing, multiplier

    def _scale_to_exante_volatility(
        self, date: pd.Timestamp, targets: dict[str, int], equity: float, target_vol: float
    ) -> tuple[float, float]:
        config = self.portfolio.get("covariance_scaling", {})
        if not config.get("enabled", False) or len(targets) < 2:
            return float("nan"), 1.0
        contracts = list(targets)
        instruments = [self._instrument_for_contract(contract) for contract in contracts]
        window = self.price_changes.loc[:date, instruments].tail(int(config["lookback_days"])).dropna()
        if len(window) < int(config["min_periods"]):
            return float("nan"), 1.0
        point_values = np.array(
            [self._contract_value(contract, "point_value", self._fallback(instrument)[0])
             for contract, instrument in zip(contracts, instruments)],
            dtype=float,
        )
        quantities = np.array([targets[contract] for contract in contracts], dtype=float)
        monetary_changes = window.to_numpy(dtype=float) * point_values
        covariance = np.cov(monetary_changes, rowvar=False, ddof=1)
        if np.ndim(covariance) != 2 or not np.isfinite(covariance).all():
            return float("nan"), 1.0
        daily_variance = float(quantities @ covariance @ quantities)
        if daily_variance <= 0:
            return float("nan"), 1.0
        exante_vol = math.sqrt(daily_variance * float(self.volatility["annualization_days"])) / equity
        raw_multiplier = target_vol / exante_vol
        multiplier = float(np.clip(
            raw_multiplier, float(config["minimum_multiplier"]), float(config["maximum_multiplier"])
        ))
        self._scale_integer_targets(targets, multiplier)
        return exante_vol, multiplier

    def _apply_position_buffers(
        self, date: pd.Timestamp, optimal: dict[str, int], positions: dict[str, int]
    ) -> tuple[dict[str, int], dict[str, int]]:
        fraction = float(self.portfolio["position_buffer_fraction"])
        desired: dict[str, int] = {}
        diagnostics = {"evaluations": 0, "holds": 0, "trades": 0, "roll_bypasses": 0}
        # Contract changes are rolls and bypass the risk buffer.
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
        return (
            {contract: quantity for contract, quantity in desired.items() if quantity != 0},
            diagnostics,
        )

    def _scale_for_portfolio_constraints(
        self, date: pd.Timestamp, targets: dict[str, int], equity: float
    ) -> dict[str, bool]:
        diagnostics = {
            "commodity_margin_scaled": False,
            "total_margin_scaled": False,
            "commodity_leverage_scaled": False,
        }
        commodity, _ = self._split_exempt_positions(targets)
        commodity_margin = self._margin_required(date, commodity)
        legacy_margin = float(self.portfolio.get("max_margin_utilization", 1.0))
        commodity_margin_limit = equity * float(
            self.portfolio.get("max_commodity_margin_utilization", legacy_margin)
        )
        if commodity_margin > commodity_margin_limit and commodity_margin > 0:
            self._scale_subset_targets(targets, set(commodity), commodity_margin_limit / commodity_margin)
            diagnostics["commodity_margin_scaled"] = True

        commodity, _ = self._split_exempt_positions(targets)
        commodity_gross = self._gross_notional(date, commodity)
        commodity_gross_limit = equity * float(self.portfolio.get(
            "max_commodity_gross_notional_leverage",
            self.portfolio.get("max_gross_notional_leverage", float("inf")),
        ))
        if commodity_gross > commodity_gross_limit and commodity_gross > 0:
            self._scale_subset_targets(targets, set(commodity), commodity_gross_limit / commodity_gross)
            diagnostics["commodity_leverage_scaled"] = True

        total_margin = self._margin_required(date, targets)
        total_margin_limit = equity * float(
            self.portfolio.get("max_total_margin_utilization", legacy_margin)
        )
        if total_margin > total_margin_limit and total_margin > 0:
            commodity, exempt = self._split_exempt_positions(targets)
            commodity_margin = self._margin_required(date, commodity)
            exempt_margin = self._margin_required(date, exempt)
            available_for_exempt = max(0.0, total_margin_limit - commodity_margin)
            if exempt_margin > 0:
                self._scale_subset_targets(
                    targets, set(exempt), available_for_exempt / exempt_margin
                )
            else:
                self._scale_integer_targets(targets, total_margin_limit / total_margin)
            diagnostics["total_margin_scaled"] = True
        return diagnostics

    def _split_exempt_positions(
        self, positions: dict[str, int]
    ) -> tuple[dict[str, int], dict[str, int]]:
        commodity: dict[str, int] = {}
        exempt: dict[str, int] = {}
        for contract, quantity in positions.items():
            instrument = self._instrument_for_contract(contract)
            sector = self.sector_by_instrument.get(instrument)
            (exempt if sector in self.leverage_exempt_sectors else commodity)[contract] = quantity
        return commodity, exempt

    @staticmethod
    def _scale_subset_targets(
        targets: dict[str, int], contracts: set[str], scale: float
    ) -> None:
        for contract in contracts:
            if contract not in targets:
                continue
            quantity = targets[contract]
            targets[contract] = int(math.copysign(math.floor(abs(quantity) * scale), quantity))
            if targets[contract] == 0:
                targets.pop(contract)

    @staticmethod
    def _scale_integer_targets(targets: dict[str, int], scale: float) -> None:
        for contract, quantity in list(targets.items()):
            targets[contract] = int(math.copysign(math.floor(abs(quantity) * scale), quantity))
            if targets[contract] == 0:
                targets.pop(contract)

    def _margin_required(self, date: pd.Timestamp, positions: dict[str, int]) -> float:
        total = 0.0
        for contract, quantity in positions.items():
            key = (date, contract)
            if key not in self.bars.index:
                continue
            bar = self.bars.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            instrument = self._instrument_for_contract(contract)
            point_value = self._value(bar, "point_value", self._fallback(instrument)[0])
            reported = max(
                self._value(bar, "long_margin_rate", 0.0),
                self._value(bar, "short_margin_rate", 0.0),
            )
            # M4: prefer real daily margin rate when present; fall back to the
            # static per-instrument rate only when no real rate is available.
            # (Previously max(reported, fallback) kept the static rate because
            # real rates 0.05–0.22 are usually BELOW the static 0.12–0.18.)
            base_rate = reported if reported > 0 else self._fallback(instrument)[2]
            effective_rate = base_rate * float(self.portfolio["broker_margin_multiplier"])
            total += abs(quantity) * self._mark_price(bar) * point_value * effective_rate
        return total

    def _gross_notional(self, date: pd.Timestamp, positions: dict[str, int]) -> float:
        total = 0.0
        for contract, quantity in positions.items():
            key = (date, contract)
            if key not in self.bars.index:
                continue
            bar = self.bars.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            point_value = self._value(bar, "point_value", self._fallback(self._instrument_for_contract(contract))[0])
            total += abs(quantity) * self._mark_price(bar) * point_value
        return total

    def _commission(self, bar: pd.Series, quantity: int, price: float, point_value: float) -> float:
        lots = abs(quantity)
        fixed = self._value(bar, "trading_fee", 0.0) * lots
        # Tushare trading_fee_rate is reported in ten-thousandths for many exchanges.
        reported_rate = self._value(bar, "trading_fee_rate", 0.0) / 10000.0
        reported = fixed + lots * price * point_value * reported_rate
        fallback = max(
            lots * float(self.execution["fallback_commission_per_lot"]),
            lots * price * point_value * float(self.execution["fallback_commission_rate"]),
        )
        return max(reported * 1.2, fallback)

    @staticmethod
    def _is_adverse_limit_lock(bar: pd.Series, quantity: int) -> bool:
        open_price = float(bar["open"])
        locked = np.isfinite(bar.get("high", np.nan)) and np.isfinite(bar.get("low", np.nan)) and float(bar["high"]) == float(bar["low"])
        if not locked:
            return False
        if quantity > 0 and np.isfinite(bar.get("upper_limit", np.nan)):
            return open_price >= float(bar["upper_limit"])
        if quantity < 0 and np.isfinite(bar.get("lower_limit", np.nan)):
            return open_price <= float(bar["lower_limit"])
        return False

    def _update_previous_closes(
        self, date: pd.Timestamp, previous_closes: dict[str, float], contracts: set[str]
    ) -> None:
        for contract in contracts:
            key = (date, contract)
            if key in self.bars.index:
                bar = self.bars.loc[key]
                if isinstance(bar, pd.DataFrame):
                    bar = bar.iloc[-1]
                mark = self._mark_price(bar)
                if np.isfinite(mark):
                    previous_closes[contract] = mark

    def _order_reason(
        self, date: pd.Timestamp, contract: str, instrument: str, positions: dict[str, int]
    ) -> str:
        held_contracts = [item for item in positions if self._instrument_for_contract(item) == instrument]
        mapped = self.mapping.get((date, instrument))
        if held_contracts and mapped and any(item != mapped for item in held_contracts):
            return "roll"
        return "signal_or_risk_rebalance"

    def _instrument_for_contract(self, contract: str) -> str:
        if contract in self.contract_meta.index:
            value = self.contract_meta.loc[contract, "instrument"]
            return str(value.iloc[-1] if isinstance(value, pd.Series) else value)
        letters = "".join(character for character in contract.split(".")[0] if character.isalpha())
        return letters.upper()

    def _contract_value(self, contract: str, column: str, fallback: float) -> float:
        if contract in self.contract_meta.index and column in self.contract_meta:
            value = self.contract_meta.loc[contract, column]
            if isinstance(value, pd.Series):
                value = value.iloc[-1]
            if pd.notna(value):
                return float(value)
        return fallback

    @staticmethod
    def _value(row: pd.Series, key: str, fallback: float) -> float:
        value = row.get(key, np.nan)
        return float(value) if pd.notna(value) else float(fallback)

    @staticmethod
    def _mark_price(bar: pd.Series) -> float:
        """Use exchange settlement for futures variation margin; close is fallback."""
        settlement = bar.get("settlement", np.nan)
        if pd.notna(settlement) and float(settlement) > 0:
            return float(settlement)
        return float(bar["close"])

    @staticmethod
    def _rejection(
        date: pd.Timestamp, order: PendingOrder, reason: str, remainder: int | None = None
    ) -> dict[str, Any]:
        return {
            "date": date, "created_date": order.created_date, "contract": order.contract,
            "instrument": order.instrument, "quantity_remaining": order.quantity if remainder is None else remainder,
            "attempt": order.attempts, "reason": reason,
        }

    @staticmethod
    def _fallback(instrument: str) -> tuple[float, float, float]:
        from .universe import FALLBACK_ECONOMICS

        return FALLBACK_ECONOMICS.get(instrument, (1.0, 1.0, 0.18))


def buffered_position(current: int, optimal: int, fraction: float) -> int:
    """Carver-style no-trade band; trade only to the nearest band edge."""
    if optimal == 0:
        return 0
    if fraction <= 0:
        return int(optimal)
    width = max(1.0, abs(optimal) * fraction)
    lower, upper = optimal - width, optimal + width
    if lower <= current <= upper:
        return int(current)
    if current < lower:
        return int(math.ceil(lower))
    return int(math.floor(upper))
