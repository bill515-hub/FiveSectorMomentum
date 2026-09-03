from __future__ import annotations

from dataclasses import dataclass

from .engine_v3 import BacktestEngineV3, BacktestScenarioV3


@dataclass(frozen=True)
class V4Scenario:
    label: str
    stage: str
    family: str
    horizons: tuple[int, ...]
    aggregation: str = "single"  # single / raw / scaled
    skip_recent_days: int = 0
    effective_window_days: int | None = None
    candidate: bool = True
    parent_label: str | None = None
    omitted_horizon: int | None = None
    slippage_model: str = "normal"
    fixed_slippage_ticks: float = 2.0

    @property
    def name(self) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.label)
        return f"{self.stage}__{safe}"

    def execution_scenario(self) -> BacktestScenarioV3:
        return BacktestScenarioV3(
            label=self.label,
            stage=self.stage,
            annual_vol_target=0.275,
            unfilled_mode="cancel_recalculate",
            fee_multiplier=1.5,
            slippage_model=self.slippage_model,
            fixed_slippage_ticks=self.fixed_slippage_ticks,
            rebalance_mode="hybrid",
            buffer_fraction=0.10,
            emergency_vol_ratio=1.20,
        )


class BacktestEngineV4(BacktestEngineV3):
    """Frozen-v3 execution engine with explicit v4 baseline assertions."""

    def __init__(self, settings, data, signals, fee_schedule):
        if settings.raw.get("version") != "v4":
            raise ValueError("BacktestEngineV4 requires a v4 config")
        super().__init__(settings, data, signals, fee_schedule)

    def run_v4(self, scenario: V4Scenario):
        execution = scenario.execution_scenario()
        if (
            execution.fee_multiplier != 1.5
            or execution.rebalance_mode != "hybrid"
            or execution.buffer_fraction != 0.10
            or execution.emergency_vol_ratio != 1.20
        ):
            raise AssertionError("v4 execution baseline must remain frozen to v3")
        result = super().run(execution)
        # v3 account values are deterministic, but rows emitted while iterating a
        # set can have process-dependent order.  Canonical ordering makes v4
        # files byte-stable without changing any trade, position or cash flow.
        sort_keys = {
            "equity": ["date"],
            "positions": ["date", "contract", "instrument"],
            "targets": ["date", "contract", "instrument"],
            "orders": ["created_date", "contract", "instrument", "quantity", "reason"],
            "fills": ["date", "created_date", "contract", "instrument", "attempt", "transaction_type"],
            "rejections": ["date", "created_date", "contract", "instrument", "reason"],
            "pnl_by_instrument": ["date", "contract", "instrument"],
        }
        for attribute, keys in sort_keys.items():
            frame = getattr(result, attribute)
            usable = [key for key in keys if key in frame.columns]
            if usable and not frame.empty:
                setattr(result, attribute, frame.sort_values(usable, kind="stable").reset_index(drop=True))
        return result
