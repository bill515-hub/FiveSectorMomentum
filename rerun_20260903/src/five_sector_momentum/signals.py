from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .data_pipeline import DataBundle
from .settings import Settings


@dataclass
class SignalBundle:
    scores: pd.DataFrame
    daily_price_vol: pd.DataFrame
    eligibility: pd.DataFrame
    liquidity: pd.DataFrame
    selections: pd.DataFrame
    directions: pd.DataFrame
    diagnostics: dict[str, Any]


def build_signals(settings: Settings, data: DataBundle) -> SignalBundle:
    signal_config = settings.section("signal")
    vol_config = settings.section("volatility")
    prices = (
        data.adjusted_prices.pivot(index="date", columns="instrument", values="adjusted_price")
        .sort_index()
    )
    price_changes = prices.diff()
    lookback = int(signal_config["lookback_days"])
    annualization = float(signal_config["annualization_days"])
    rolling_mean = price_changes.rolling(lookback, min_periods=lookback).mean()
    rolling_std = price_changes.rolling(lookback, min_periods=lookback).std(ddof=1)
    scores_wide = rolling_mean.divide(rolling_std.replace(0.0, np.nan)) * np.sqrt(annualization)
    daily_vol_wide = robust_price_volatility(price_changes, vol_config)
    eligibility_wide, median_volume, median_oi = build_liquidity_measures(
        data, settings.section("eligibility"), prices.index
    )

    scores = _wide_to_long(scores_wide, "score")
    daily_vol = _wide_to_long(daily_vol_wide, "daily_price_vol")
    eligibility = _wide_to_long(eligibility_wide, "eligible")
    liquidity = _wide_to_long(median_volume, "median_volume").merge(
        _wide_to_long(median_oi, "median_open_interest"),
        on=["date", "instrument"], how="outer",
    )
    selections, directions, selection_diag = _weekly_select(
        scores_wide, eligibility_wide, data.instrument_meta, signal_config
    )
    diagnostics = {
        "method": "annualized_sharpe_of_absolute_price_differences",
        "lookback_days": lookback,
        "annualization_days": annualization,
        "score_start_by_instrument": {
            column: (str(scores_wide[column].first_valid_index().date()) if scores_wide[column].first_valid_index() is not None else None)
            for column in scores_wide
        },
        **selection_diag,
    }
    diagnostics["eligible_days_by_instrument"] = {
        column: int(eligibility_wide.loc[:, column].sum()) for column in eligibility_wide
    }
    return SignalBundle(scores, daily_vol, eligibility, liquidity, selections, directions, diagnostics)


def build_liquidity_eligibility(
    data: DataBundle, config: dict[str, Any], dates: pd.DatetimeIndex
) -> pd.DataFrame:
    eligibility, _, _ = build_liquidity_measures(data, config, dates)
    return eligibility


def build_liquidity_measures(
    data: DataBundle, config: dict[str, Any], dates: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mapped = data.mapping.merge(
        data.bars[["date", "ts_code", "volume", "oi"]],
        left_on=["date", "contract"], right_on=["date", "ts_code"], how="left",
    )
    volume = mapped.pivot(index="date", columns="instrument", values="volume").reindex(dates)
    open_interest = mapped.pivot(index="date", columns="instrument", values="oi").reindex(dates)
    lookback = int(config["liquidity_lookback_days"])
    minimum = int(config["liquidity_min_periods"])
    median_volume = volume.rolling(lookback, min_periods=minimum).median()
    median_oi = open_interest.rolling(lookback, min_periods=minimum).median()
    eligibility = (
        median_volume.ge(float(config["min_median_volume"]))
        & median_oi.ge(float(config["min_median_open_interest"]))
    )
    return eligibility, median_volume, median_oi


def robust_price_volatility(price_changes: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    span = int(config["ewma_span_days"])
    min_periods = int(config["min_periods"])
    volatility = price_changes.ewm(span=span, min_periods=min_periods, adjust=True).std(bias=False)
    volatility = volatility.clip(lower=float(config["absolute_min"]))
    if config.get("floor_enabled", True):
        floor = volatility.rolling(
            int(config["floor_lookback_days"]),
            min_periods=int(config["floor_min_periods"]),
        ).quantile(float(config["floor_quantile"]))
        volatility = volatility.combine(floor, np.maximum)
    return volatility


def _weekly_select(
    scores: pd.DataFrame, eligibility: pd.DataFrame,
    instrument_meta: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if scores.empty:
        return pd.DataFrame(), pd.DataFrame(), {"weekly_signal_dates": 0}
    week_keys = scores.index.to_period("W-FRI")
    signal_dates = scores.groupby(week_keys).apply(lambda frame: frame.index[-1])
    meta = instrument_meta.set_index("instrument")
    instruments = list(meta.index)
    current = pd.Series(0, index=instruments, dtype=int)
    current_signal_date = pd.NaT
    direction_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    signal_date_set = set(pd.DatetimeIndex(signal_dates.values))

    for date in scores.index:
        if date in signal_date_set:
            current[:] = 0
            current_signal_date = date
            date_scores = scores.loc[date].where(eligibility.loc[date].reindex(scores.columns).fillna(False))
            for sector, sector_meta in meta.groupby("sector"):
                members = list(sector_meta.index)
                eligible = date_scores.reindex(members).dropna()
                mode = sector_meta["mode"].iloc[0]
                if mode == "cross_sectional":
                    if len(eligible) < int(config["min_eligible_instruments"]):
                        insufficient.append({"date": str(date.date()), "sector": sector, "eligible": len(eligible)})
                        continue
                    strongest = eligible.idxmax()
                    weakest = eligible.idxmin()
                    if eligible[strongest] > float(config["long_threshold"]):
                        current[strongest] = 1
                        selection_rows.append(_selection_row(date, sector, strongest, 1, eligible[strongest], "strongest"))
                    if weakest != strongest and eligible[weakest] < float(config["short_threshold"]):
                        current[weakest] = -1
                        selection_rows.append(_selection_row(date, sector, weakest, -1, eligible[weakest], "weakest"))
                else:
                    for instrument, score in eligible.items():
                        direction = int(score > float(config["long_threshold"])) - int(score < float(config["short_threshold"]))
                        current[instrument] = direction
                        if direction:
                            selection_rows.append(_selection_row(date, sector, instrument, direction, score, "absolute"))
        for instrument, direction in current.items():
            direction_rows.append(
                {"date": date, "signal_date": current_signal_date, "instrument": instrument,
                 "sector": meta.loc[instrument, "sector"], "direction": int(direction)}
            )
    selections = pd.DataFrame(selection_rows)
    directions = pd.DataFrame(direction_rows)
    diagnostics = {
        "weekly_signal_dates": len(signal_date_set),
        "first_signal_date": str(min(signal_date_set).date()) if signal_date_set else None,
        "last_signal_date": str(max(signal_date_set).date()) if signal_date_set else None,
        "insufficient_cross_sectional": insufficient,
    }
    return selections, directions, diagnostics


def _selection_row(
    date: pd.Timestamp, sector: str, instrument: str, direction: int, score: float, role: str
) -> dict[str, Any]:
    return {
        "signal_date": date, "sector": sector, "instrument": instrument,
        "direction": direction, "score": float(score), "role": role,
    }


def _wide_to_long(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    return (
        frame.rename_axis(index="date", columns="instrument").stack(future_stack=True)
        .rename(value_name).reset_index()
    )
