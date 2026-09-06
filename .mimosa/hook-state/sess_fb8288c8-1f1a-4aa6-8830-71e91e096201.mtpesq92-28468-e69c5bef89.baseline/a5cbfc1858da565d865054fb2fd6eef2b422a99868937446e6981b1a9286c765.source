from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .data_pipeline import DataBundle
from .settings import Settings
from .signals import (
    SignalBundle, _wide_to_long, _weekly_select,
    build_liquidity_measures, robust_price_volatility,
)


@dataclass
class ForecastLibraryV4:
    prices: pd.DataFrame
    price_changes: pd.DataFrame
    raw_regular: dict[int, pd.DataFrame]
    raw_skip5: dict[int, pd.DataFrame]
    raw_reference_252: pd.DataFrame
    raw_250_minus_20: pd.DataFrame
    scaled_regular: dict[int, pd.DataFrame]
    scalars: dict[int, pd.Series]
    daily_vol: pd.DataFrame
    eligibility: pd.DataFrame
    median_volume: pd.DataFrame
    median_open_interest: pd.DataFrame


def price_diff_sharpe(
    price_changes: pd.DataFrame, window_days: int, annualization_days: float = 252.0,
    skip_recent_days: int = 0,
) -> pd.DataFrame:
    """Annualized Sharpe of absolute price differences with an explicit boundary.

    At date t, shift(skip) makes the newest observation ΔP[t-skip].  Requiring
    min_periods=window prevents partial-window or future-filled forecasts.
    """
    if window_days < 2 or skip_recent_days < 0:
        raise ValueError("window_days must be >=2 and skip_recent_days must be >=0")
    usable = price_changes.shift(int(skip_recent_days))
    mean = usable.rolling(int(window_days), min_periods=int(window_days)).mean()
    std = usable.rolling(int(window_days), min_periods=int(window_days)).std(ddof=1)
    return mean.divide(std.replace(0.0, np.nan)) * np.sqrt(float(annualization_days))


def causal_forecast_scale(
    raw_forecast: pd.DataFrame, target_average_absolute: float,
    minimum_history_days: int, scalar_floor: float, scalar_cap: float,
    forecast_cap: float,
) -> tuple[pd.DataFrame, pd.Series]:
    """Scale a rule using only cross-instrument forecast history through t-1."""
    daily_mean_abs = raw_forecast.abs().mean(axis=1, skipna=True)
    daily_mean_abs = daily_mean_abs.where(raw_forecast.notna().any(axis=1))
    lagged_expanding = (
        daily_mean_abs.expanding(min_periods=int(minimum_history_days)).mean().shift(1)
    )
    scalar = (float(target_average_absolute) / lagged_expanding.replace(0.0, np.nan)).clip(
        lower=float(scalar_floor), upper=float(scalar_cap)
    )
    scaled = raw_forecast.mul(scalar, axis=0).clip(
        lower=-float(forecast_cap), upper=float(forecast_cap)
    )
    return scaled, scalar.rename("forecast_scalar")


def strict_equal_weight(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight only when every registered component is present."""
    if not frames:
        raise ValueError("At least one component is required")
    total = frames[0].copy()
    valid = frames[0].notna()
    for frame in frames[1:]:
        total = total.add(frame)
        valid &= frame.notna()
    result = total / float(len(frames))
    return result.where(valid)


def build_forecast_library_v4(settings: Settings, data: DataBundle) -> ForecastLibraryV4:
    config = settings.section("v4_research")
    scaling = config["forecast_scaling"]
    annualization = float(settings.section("signal")["annualization_days"])
    prices = (
        data.adjusted_prices.pivot(index="date", columns="instrument", values="adjusted_price")
        .sort_index()
    )
    changes = prices.diff()
    horizons = [int(item) for item in config["single_horizons"]]
    skip5 = int(config["skip_recent_days"])
    raw_regular = {
        horizon: price_diff_sharpe(changes, horizon, annualization, 0)
        for horizon in horizons
    }
    raw_skip5 = {
        horizon: price_diff_sharpe(changes, horizon, annualization, skip5)
        for horizon in horizons
    }
    reference_horizon = int(config["v3_reference_lookback_days"])
    reference = price_diff_sharpe(changes, reference_horizon, annualization, 0)
    minus20 = price_diff_sharpe(
        changes,
        int(config["twelve_minus_one_effective_days"]),
        annualization,
        int(config["twelve_minus_one_skip_days"]),
    )
    scaled: dict[int, pd.DataFrame] = {}
    scalars: dict[int, pd.Series] = {}
    for horizon, frame in raw_regular.items():
        scaled[horizon], scalars[horizon] = causal_forecast_scale(
            frame,
            float(scaling["target_average_absolute_forecast"]),
            int(scaling["minimum_history_days"]),
            float(scaling["scalar_floor"]),
            float(scaling["scalar_cap"]),
            float(scaling["forecast_cap"]),
        )
    daily_vol = robust_price_volatility(changes, settings.section("volatility"))
    eligibility, median_volume, median_oi = build_liquidity_measures(
        data, settings.section("eligibility"), prices.index
    )
    return ForecastLibraryV4(
        prices, changes, raw_regular, raw_skip5, reference, minus20,
        scaled, scalars, daily_vol, eligibility, median_volume, median_oi,
    )


def signal_bundle_from_forecast(
    settings: Settings, data: DataBundle, library: ForecastLibraryV4,
    forecast: pd.DataFrame, label: str, diagnostics_extra: dict[str, Any] | None = None,
) -> SignalBundle:
    signal_config = settings.section("signal")
    scores = forecast.reindex(index=library.prices.index, columns=library.prices.columns)
    selections, directions, selection_diag = _weekly_select(
        scores, library.eligibility, data.instrument_meta, signal_config
    )
    diagnostics: dict[str, Any] = {
        "method": "v4_annualized_sharpe_of_absolute_price_differences",
        "forecast_label": label,
        "annualization_days": float(signal_config["annualization_days"]),
        "score_start_by_instrument": {
            column: (
                str(scores[column].first_valid_index().date())
                if scores[column].first_valid_index() is not None else None
            ) for column in scores
        },
        **selection_diag,
    }
    if diagnostics_extra:
        diagnostics.update(diagnostics_extra)
    diagnostics["eligible_days_by_instrument"] = {
        column: int(library.eligibility.loc[:, column].sum())
        for column in library.eligibility
    }
    liquidity = _wide_to_long(library.median_volume, "median_volume").merge(
        _wide_to_long(library.median_open_interest, "median_open_interest"),
        on=["date", "instrument"], how="outer",
    )
    return SignalBundle(
        scores=_wide_to_long(scores, "score"),
        daily_price_vol=_wide_to_long(library.daily_vol, "daily_price_vol"),
        eligibility=_wide_to_long(library.eligibility, "eligible"),
        liquidity=liquidity,
        selections=selections,
        directions=directions,
        diagnostics=diagnostics,
    )


def aggregate_from_library(
    library: ForecastLibraryV4, horizons: tuple[int, ...], scaled: bool,
) -> pd.DataFrame:
    source = library.scaled_regular if scaled else library.raw_regular
    return strict_equal_weight([source[int(horizon)] for horizon in horizons])

