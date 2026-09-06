from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class FillLeg:
    trade_type: str
    lots: int


def split_cross_zero(position: int, order: int) -> list[FillLeg]:
    if order == 0:
        return []
    if position == 0 or position * order > 0:
        return [FillLeg("OPEN", abs(order))]
    closing = min(abs(position), abs(order))
    legs = [FillLeg("CLOSE_YESTERDAY", closing)]
    opening = abs(order) - closing
    if opening:
        legs.append(FillLeg("OPEN", opening))
    return legs


def calculate_exchange_fee(
    *, trade_type: str, lots: int, price: float, multiplier: float,
    fixed_per_lot: float = 0.0, rate: float = 0.0, customer_multiplier: float = 1.5,
) -> float:
    if trade_type not in {"OPEN", "CLOSE_YESTERDAY", "CLOSE_TODAY"}:
        raise ValueError("unsupported trade type")
    return abs(lots) * (fixed_per_lot + price * multiplier * rate) * customer_multiplier


def adverse_fill_price(open_price: float, ticks: int, tick_size: float, side: int) -> float:
    if ticks < 0 or int(ticks) != ticks:
        raise ValueError("slippage must be a non-negative integer tick count")
    return open_price + (1 if side > 0 else -1) * ticks * tick_size


def limit_allows(side: int, open_price: float, upper: float, lower: float) -> bool:
    if side > 0:
        return open_price < upper
    if side < 0:
        return open_price > lower
    return True


def participation_fill(requested_lots: int, volume: float | None, fraction: float = 0.05, proxy: int = 10000) -> tuple[int, int]:
    usable = proxy if volume is None else max(float(volume), 0.0)
    capacity = int(usable * fraction)
    fill = min(abs(requested_lots), capacity) * (1 if requested_lots >= 0 else -1)
    return fill, requested_lots - fill


def net_targets(targets: Iterable[tuple[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for contract, lots in targets:
        result[contract] = result.get(contract, 0) + int(lots)
    return {contract: lots for contract, lots in sorted(result.items()) if lots != 0}


def cap_target(target: int, caps: Iterable[int]) -> int:
    magnitude = min([abs(target), *(max(0, int(cap)) for cap in caps)])
    return magnitude if target >= 0 else -magnitude


def utilization_breach(commodity: float, total: float, commodity_cap: float = 0.65, total_cap: float = 0.78) -> dict[str, bool]:
    return {
        "commodity_breach": commodity > commodity_cap,
        "total_breach": total > total_cap,
        "action_is_forced_liquidation": False,
        "recompute_next_standard_target": commodity > commodity_cap or total > total_cap,
    }


def account_state(equity: float) -> str:
    return "ACCOUNT_INSOLVENT" if equity <= 0 else "ACTIVE"


def matched_roll_order(old_position: int, new_target: int) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    if old_position:
        result.append(("CLOSE_OLD", -old_position))
    if new_target:
        result.append(("OPEN_NEW", new_target))
    return result


def causal_point_sharpe(price: pd.Series, window: int, skip: int = 0) -> pd.Series:
    differences = price.diff()
    shifted = differences.shift(skip)
    mean = shifted.rolling(window=window, min_periods=window).mean()
    std = shifted.rolling(window=window, min_periods=window).std(ddof=1)
    return mean.div(std).mul(252 ** 0.5)

