from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EventReason(StrEnum):
    SIGNAL_REBALANCE = "SIGNAL_REBALANCE"
    CROSS_SECTION_SWITCH = "CROSS_SECTION_SWITCH"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    CROSS_ZERO_REVERSAL = "CROSS_ZERO_REVERSAL"
    MAIN_CONTRACT_ROLL = "MAIN_CONTRACT_ROLL"
    VOLATILITY_TARGET_ADJUSTMENT = "VOLATILITY_TARGET_ADJUSTMENT"
    EMERGENCY_VOLATILITY_REDUCTION = "EMERGENCY_VOLATILITY_REDUCTION"
    MARGIN_TARGET_REDUCTION = "MARGIN_TARGET_REDUCTION"
    LIQUIDITY_TARGET_REDUCTION = "LIQUIDITY_TARGET_REDUCTION"
    REJECTED_LIMIT = "REJECTED_LIMIT"
    ACCOUNT_INSOLVENT = "ACCOUNT_INSOLVENT"


@dataclass(frozen=True)
class MarginTargetReductionEvent:
    date: str
    instrument: str
    target_before: int
    target_after: int


@dataclass(frozen=True)
class MarginUtilizationBreachDiagnostic:
    date: str
    commodity_utilization: float
    total_utilization: float


@dataclass(frozen=True)
class AccountInsolventEvent:
    date: str
    equity: float
    state: str = EventReason.ACCOUNT_INSOLVENT

