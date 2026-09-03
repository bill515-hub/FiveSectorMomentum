from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from .settings import Settings
from .storage import read_frame, write_frame, write_json
from .universe import FALLBACK_ECONOMICS, instrument_frame, instruments_from_config


@dataclass
class DataBundle:
    bars: pd.DataFrame
    mapping: pd.DataFrame
    multiple_prices: pd.DataFrame
    adjusted_prices: pd.DataFrame
    contract_meta: pd.DataFrame
    instrument_meta: pd.DataFrame
    diagnostics: dict[str, Any]


def normalize_and_build(settings: Settings) -> DataBundle:
    raw_root = settings.data_root / "raw" / "tushare"
    bars = _normalize_bars(read_frame(raw_root / "fut_daily"))
    basics = read_frame(raw_root / "fut_basic")
    vendor_mapping = read_frame(raw_root / "fut_mapping")
    settlements = _read_optional(raw_root / "fut_settle")
    limits = _read_optional(raw_root / "ft_limit")

    specs = instruments_from_config(settings.section("universe"))
    instrument_meta = instrument_frame(specs)
    contract_meta = _contract_metadata(basics, instrument_meta)
    bars = _merge_daily_contract_data(bars, settlements, limits, contract_meta)
    mapping, mapping_diag = build_mapping(settings, bars, vendor_mapping, contract_meta, instrument_meta)
    multiple, adjusted, stitch_diag = build_panama_prices(settings, bars, mapping)

    diagnostics = {"mapping": mapping_diag, "panama": stitch_diag}
    output = settings.data_root / settings.section("data").get("normalized_subdir", "normalized")
    paths = {
        "bars": write_frame(bars, output / "bars"),
        "mapping": write_frame(mapping, output / "mapping"),
        "multiple_prices": write_frame(multiple, output / "multiple_prices"),
        "adjusted_prices": write_frame(adjusted, output / "adjusted_prices"),
        "contract_meta": write_frame(contract_meta, output / "contract_meta"),
        "instrument_meta": write_frame(instrument_meta, output / "instrument_meta"),
    }
    diagnostics["files"] = {key: str(value) for key, value in paths.items()}
    write_json(diagnostics, output / "diagnostics.json")
    return DataBundle(bars, mapping, multiple, adjusted, contract_meta, instrument_meta, diagnostics)


def load_bundle(settings: Settings) -> DataBundle:
    root = settings.data_root / settings.section("data").get("normalized_subdir", "normalized")
    from .storage import read_json

    return DataBundle(
        bars=read_frame(root / "bars"),
        mapping=read_frame(root / "mapping"),
        multiple_prices=read_frame(root / "multiple_prices"),
        adjusted_prices=read_frame(root / "adjusted_prices"),
        contract_meta=read_frame(root / "contract_meta"),
        instrument_meta=read_frame(root / "instrument_meta"),
        diagnostics=read_json(root / "diagnostics.json"),
    )


def _read_optional(base: Path) -> pd.DataFrame:
    try:
        return read_frame(base)
    except FileNotFoundError:
        return pd.DataFrame()


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("No fut_daily rows were downloaded")
    result = frame.rename(columns={"trade_date": "date", "vol": "volume", "settle": "settlement"}).copy()
    result["date"] = pd.to_datetime(result["date"])
    result["instrument"] = result["instrument"].astype(str).str.upper()
    numeric = [
        "open", "high", "low", "close", "settlement", "pre_close", "pre_settle",
        "volume", "amount", "oi", "oi_chg",
    ]
    for column in numeric:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    # Tushare sometimes uses zero OHLC on contracts with no actual trade while
    # retaining a reference close.  Zero is not an executable futures price.
    for column in ["open", "high", "low", "close", "settlement"]:
        if column in result:
            result.loc[result[column].le(0), column] = np.nan
    result = result.drop_duplicates(["date", "ts_code"], keep="last")
    return result.sort_values(["date", "instrument", "ts_code"]).reset_index(drop=True)


def _contract_metadata(basics: pd.DataFrame, instrument_meta: pd.DataFrame) -> pd.DataFrame:
    if basics.empty:
        raise ValueError("fut_basic is required to establish contract economics")
    meta = basics.copy()
    meta["instrument"] = meta["fut_code"].astype(str).str.upper()
    meta = meta.merge(instrument_meta, on=["instrument", "exchange"], how="inner")
    for column in ["list_date", "delist_date", "last_ddate"]:
        if column in meta:
            meta[column] = pd.to_datetime(meta[column], errors="coerce")
    for column in ["multiplier", "per_unit"]:
        meta[column] = pd.to_numeric(meta.get(column), errors="coerce")
    # For Chinese commodity futures per_unit is normally the CNY point value;
    # for CFFEX financial futures multiplier is the preferred field.
    preferred = np.where(
        meta["exchange"].eq("CFFEX") & meta["multiplier"].notna(),
        meta["multiplier"], meta["per_unit"],
    )
    meta["point_value"] = pd.Series(preferred, index=meta.index).fillna(meta["fallback_point_value"])
    meta["tick_size"] = meta["fallback_tick_size"]
    meta["fallback_margin_rate"] = meta["fallback_margin_rate"].astype(float)
    columns = [
        "ts_code", "instrument", "exchange", "name", "list_date", "delist_date", "last_ddate",
        "point_value", "tick_size", "fallback_margin_rate", "sector", "mode",
    ]
    return meta[[column for column in columns if column in meta]].drop_duplicates("ts_code")


def _merge_daily_contract_data(
    bars: pd.DataFrame, settlements: pd.DataFrame, limits: pd.DataFrame, contract_meta: pd.DataFrame
) -> pd.DataFrame:
    result = bars.copy()
    if not settlements.empty:
        settle = settlements.rename(columns={"trade_date": "date"}).copy()
        settle["date"] = pd.to_datetime(settle["date"])
        wanted = [
            "date", "ts_code", "trading_fee_rate", "trading_fee", "offset_today_fee",
            "long_margin_rate", "short_margin_rate",
        ]
        settle = settle[[column for column in wanted if column in settle]].drop_duplicates(["date", "ts_code"])
        result = result.merge(settle, on=["date", "ts_code"], how="left")
    if not limits.empty:
        limit = limits.rename(columns={"trade_date": "date", "up_limit": "upper_limit", "down_limit": "lower_limit"}).copy()
        limit["date"] = pd.to_datetime(limit["date"])
        wanted = ["date", "ts_code", "upper_limit", "lower_limit"]
        # Preserve a documented minimum margin column if the API returns one.
        wanted.extend([column for column in limit.columns if "margin" in column.lower()])
        limit = limit[[column for column in dict.fromkeys(wanted) if column in limit]].drop_duplicates(["date", "ts_code"])
        result = result.merge(limit, on=["date", "ts_code"], how="left")
    result = result.merge(
        contract_meta[["ts_code", "point_value", "tick_size", "fallback_margin_rate", "delist_date"]],
        on="ts_code", how="left",
    )
    return result.sort_values(["date", "instrument", "ts_code"]).reset_index(drop=True)


def build_mapping(
    settings: Settings, bars: pd.DataFrame, vendor_mapping: pd.DataFrame,
    contract_meta: pd.DataFrame, instrument_meta: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    roll = settings.section("roll")
    lag = int(settings.section("data").get("vendor_mapping_lag_days", 1))
    all_dates = pd.DatetimeIndex(sorted(bars["date"].unique()))
    rows: list[pd.DataFrame] = []
    vendor_used: list[str] = []
    fallback_used: list[str] = []
    forced_roll_count = 0

    vendor = vendor_mapping.copy()
    if not vendor.empty:
        vendor["date"] = pd.to_datetime(vendor["trade_date"])
    for meta in instrument_meta.itertuples(index=False):
        sub_vendor = vendor[vendor["instrument"] == meta.instrument] if not vendor.empty else pd.DataFrame()
        instrument_dates = pd.DatetimeIndex(sorted(bars.loc[bars["instrument"] == meta.instrument, "date"].unique()))
        if instrument_dates.empty:
            continue
        if not sub_vendor.empty and settings.section("data").get("use_vendor_main_mapping", True):
            series = (
                sub_vendor.sort_values("date").drop_duplicates("date", keep="last")
                .set_index("date")["mapping_ts_code"].reindex(instrument_dates).ffill()
            )
            if lag:
                series = series.shift(lag)
            mapped = pd.DataFrame({"date": instrument_dates, "contract": series.values})
            mapped["source"] = "tushare_fut_mapping_lagged" if lag else "tushare_fut_mapping"
            mapped, forced = _enforce_roll_deadline(
                mapped, bars[bars["instrument"] == meta.instrument], contract_meta,
                int(roll["minimum_days_to_expiry"]), bool(roll["forbid_backward_roll"]),
            )
            forced_roll_count += forced
            vendor_used.append(meta.instrument)
        else:
            mapped = _oi_fallback_mapping(
                bars[bars["instrument"] == meta.instrument], contract_meta,
                int(roll["minimum_days_to_expiry"]), int(roll["fallback_confirmation_days"]),
                float(roll["fallback_switch_ratio"]), bool(roll["forbid_backward_roll"]),
            )
            mapped["source"] = "open_interest_fallback"
            fallback_used.append(meta.instrument)
        mapped["instrument"] = meta.instrument
        rows.append(mapped.dropna(subset=["contract"]))
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    result = result.sort_values(["instrument", "date"]).reset_index(drop=True)
    diagnostics = {
        "vendor_mapping_lag_days": lag,
        "vendor_used": vendor_used,
        "fallback_used": fallback_used,
        "forced_roll_deadline_overrides": forced_roll_count,
        "unmapped_instruments": sorted(set(instrument_meta["instrument"]) - set(result.get("instrument", []))),
        "rows": len(result),
    }
    return result, diagnostics


def _enforce_roll_deadline(
    mapped: pd.DataFrame, instrument_bars: pd.DataFrame, contract_meta: pd.DataFrame,
    minimum_days: int, forbid_backward: bool,
) -> tuple[pd.DataFrame, int]:
    """Keep the vendor main contract except when it is no longer safely executable.

    Tushare's mapping can remain on a delivery-month contract until its liquidity has
    almost disappeared.  Because targets formed at today's close execute tomorrow,
    the mapped contract must still have enough calendar runway.  On a deadline or a
    missing-bar day, use the highest-OI live contract with at least ``minimum_days``
    remaining.  This is an execution guard, not an alternative main-contract rule.
    """
    if mapped.empty:
        return mapped, 0
    expiry = contract_meta.set_index("ts_code")["delist_date"].to_dict()
    by_date = {date: group for date, group in instrument_bars.groupby("date")}
    result = mapped.copy()
    overrides = 0
    for index, row in result.iterrows():
        date = row["date"]
        current = row["contract"]
        current_expiry = expiry.get(current)
        days_left = (current_expiry - date).days if pd.notna(current_expiry) else None
        day = by_date.get(date)
        current_rows = day[day["ts_code"].eq(current)] if day is not None else pd.DataFrame()
        current_has_bar = (
            not current_rows.empty
            and current_rows["volume"].fillna(0).gt(0).any()
            and current_rows["close"].notna().any()
        )
        if current_has_bar and (days_left is None or days_left >= minimum_days):
            continue
        if day is None or day.empty:
            continue
        candidates = day.copy()
        candidates["delist_date_guard"] = candidates["ts_code"].map(expiry)
        candidates["days_left_guard"] = (candidates["delist_date_guard"] - date).dt.days
        candidates = candidates[
            candidates["days_left_guard"].ge(minimum_days)
            & candidates["oi"].fillna(0).gt(0)
            & candidates["volume"].fillna(0).gt(0)
        ]
        if forbid_backward and pd.notna(current_expiry):
            candidates = candidates[candidates["delist_date_guard"] > current_expiry]
        if candidates.empty:
            continue
        replacement = candidates.sort_values(["oi", "volume"], ascending=False).iloc[0]["ts_code"]
        if replacement != current:
            result.at[index, "contract"] = replacement
            result.at[index, "source"] = "tushare_with_expiry_guard"
            overrides += 1
    return result, overrides


def _oi_fallback_mapping(
    bars: pd.DataFrame, contract_meta: pd.DataFrame, min_days: int,
    confirmation_days: int, switch_ratio: float, forbid_backward: bool,
) -> pd.DataFrame:
    data = bars.merge(contract_meta[["ts_code", "delist_date"]], on="ts_code", how="left", suffixes=("", "_meta"))
    if "delist_date_meta" in data:
        data["delist_date"] = data["delist_date"].fillna(data["delist_date_meta"])
    data["days_to_expiry"] = (data["delist_date"] - data["date"]).dt.days
    eligible = data[(data["days_to_expiry"].isna() | (data["days_to_expiry"] >= min_days)) & data["oi"].gt(0)]
    candidates = (
        eligible.sort_values(["date", "oi"], ascending=[True, False])
        .drop_duplicates("date").set_index("date")["ts_code"]
    )
    by_date = {date: group.set_index("ts_code") for date, group in eligible.groupby("date")}
    current: str | None = None
    proposed: str | None = None
    count = 0
    rows = []
    expiry = contract_meta.set_index("ts_code")["delist_date"].to_dict()
    for date, candidate in candidates.items():
        if current is None:
            current = candidate
        elif candidate != current:
            current_oi = by_date[date]["oi"].get(current, 0.0)
            candidate_oi = by_date[date]["oi"].get(candidate, 0.0)
            backwards = forbid_backward and pd.notna(expiry.get(current)) and pd.notna(expiry.get(candidate)) and expiry[candidate] <= expiry[current]
            if not backwards and candidate_oi >= current_oi * switch_ratio:
                if proposed == candidate:
                    count += 1
                else:
                    proposed, count = candidate, 1
                if count >= confirmation_days:
                    current, proposed, count = candidate, None, 0
            else:
                proposed, count = None, 0
        else:
            proposed, count = None, 0
        rows.append({"date": date, "contract": current})
    return pd.DataFrame(rows)


def build_panama_prices(
    settings: Settings, bars: pd.DataFrame, mapping: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    price_column = settings.section("signal")["price"]
    lookup = bars.set_index(["date", "ts_code"])
    multiple_rows: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    roll_count = 0

    for instrument, map_group in mapping.groupby("instrument"):
        group = map_group.sort_values("date").drop_duplicates("date", keep="last")
        dates = list(group["date"])
        contracts = list(group["contract"])
        sources = list(group["source"])
        next_contracts = _next_contract_by_segment(contracts)
        adjusted_values: list[float] = []
        previous_contract: str | None = None
        previous_date: pd.Timestamp | None = None
        valid_dates: list[pd.Timestamp] = []
        for date, contract, forward_contract, mapping_source in zip(dates, contracts, next_contracts, sources):
            key = (date, contract)
            if key not in lookup.index:
                continue
            current_bar = lookup.loc[key]
            if isinstance(current_bar, pd.DataFrame):
                current_bar = current_bar.iloc[-1]
            price = float(current_bar[price_column])
            volume = current_bar.get("volume", np.nan)
            if not np.isfinite(price) or (pd.notna(volume) and float(volume) <= 0):
                continue
            forward = np.nan
            if forward_contract and (date, forward_contract) in lookup.index:
                forward = float(lookup.loc[(date, forward_contract), price_column])
            if previous_contract is not None and contract != previous_contract:
                gap = _roll_gap(lookup, previous_date, previous_contract, contract, price_column)
                if gap is None:
                    failures.append(
                        {"instrument": instrument, "date": str(date.date()),
                         "old_contract": previous_contract, "new_contract": contract}
                    )
                    previous_contract, previous_date = contract, date
                    continue
                adjusted_values = [value + gap for value in adjusted_values]
                roll_count += 1
            adjusted_values.append(price)
            valid_dates.append(date)
            multiple_rows.append(
                 {"date": date, "instrument": instrument, "PRICE": price,
                 "PRICE_CONTRACT": contract, "FORWARD": forward,
                 "FORWARD_CONTRACT": forward_contract, "mapping_source": mapping_source}
            )
            previous_contract, previous_date = contract, date
        adjusted_rows.extend(
            {"date": date, "instrument": instrument, "adjusted_price": value}
            for date, value in zip(valid_dates, adjusted_values)
        )
    multiple = pd.DataFrame(multiple_rows).sort_values(["date", "instrument"]).reset_index(drop=True)
    adjusted = pd.DataFrame(adjusted_rows).sort_values(["date", "instrument"]).reset_index(drop=True)
    diagnostics = {"roll_count": roll_count, "stitch_failures": failures, "rows": len(adjusted)}
    return multiple, adjusted, diagnostics


def _next_contract_by_segment(contracts: list[str]) -> list[str | None]:
    result: list[str | None] = [None] * len(contracts)
    upcoming: str | None = None
    for index in range(len(contracts) - 1, -1, -1):
        if index + 1 < len(contracts) and contracts[index + 1] != contracts[index]:
            upcoming = contracts[index + 1]
        result[index] = upcoming
    return result


def _roll_gap(
    lookup: pd.DataFrame, previous_date: pd.Timestamp | None, old_contract: str,
    new_contract: str, price_column: str,
) -> float | None:
    if previous_date is None:
        return None
    candidate_dates = list(pd.bdate_range(end=previous_date, periods=10))[::-1]
    for date in candidate_dates:
        old_key, new_key = (date, old_contract), (date, new_contract)
        if old_key in lookup.index and new_key in lookup.index:
            old_price = float(lookup.loc[old_key, price_column])
            new_price = float(lookup.loc[new_key, price_column])
            if np.isfinite(old_price) and np.isfinite(new_price):
                return new_price - old_price
    return None
