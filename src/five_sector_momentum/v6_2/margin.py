from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


VENDOR_SOURCE = "VENDOR_DAILY_UNVERIFIED_LAGGED_FLOORED_BY_STATIC_FALLBACK"
FALLBACK_SOURCE = "STATIC_FALLBACK_PROXY"
UNIT_RULE_T = "TUSHARE_FUT_SETTLE_T_PERCENT_POINTS_DIV100"
UNIT_RULE_OTHER = "TUSHARE_FUT_SETTLE_COMMODITY_DECIMAL_IDENTITY"


def normalize_margin_cache(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_pickle(path).copy()
    raw["date"] = pd.to_datetime(raw["trade_date"].astype(str).str.replace(".0", "", regex=False), format="%Y%m%d", errors="coerce")
    usable = raw.loc[raw["source_status"].eq("tushare") & raw["date"].notna()].copy()
    usable["long_margin_raw"] = pd.to_numeric(usable["long_margin_rate"], errors="coerce")
    usable["short_margin_raw"] = pd.to_numeric(usable["short_margin_rate"], errors="coerce")
    is_t = usable["instrument"].eq("T")
    usable["long_margin_rate_decimal"] = usable["long_margin_raw"].where(~is_t, usable["long_margin_raw"] / 100.0)
    usable["short_margin_rate_decimal"] = usable["short_margin_raw"].where(~is_t, usable["short_margin_raw"] / 100.0)
    usable["unit_rule_id"] = np.where(is_t, UNIT_RULE_T, UNIT_RULE_OTHER)
    usable["source_code"] = "VENDOR_DAILY_UNVERIFIED"
    usable["known_at"] = usable["date"] + pd.Timedelta(days=1)
    columns = ["date", "ts_code", "instrument", "exchange", "long_margin_raw", "short_margin_raw", "long_margin_rate_decimal", "short_margin_rate_decimal", "unit_rule_id", "source_code", "known_at"]
    normalized = usable[columns].sort_values(["ts_code", "date"], kind="mergesort").reset_index(drop=True)
    audit = pd.DataFrame([
        {"check": "raw_rows", "value": len(raw), "passed": len(raw) == 36040},
        {"check": "valid_vendor_rows", "value": len(normalized), "passed": len(normalized) == 35873},
        {"check": "raw_requested_contract_count", "value": raw.ts_code.nunique(), "passed": raw.ts_code.nunique() == 823},
        {"check": "valid_vendor_contract_count", "value": normalized.ts_code.nunique(), "passed": normalized.ts_code.nunique() == 656},
        {"check": "explicit_no_data_contract_count", "value": raw.loc[raw.source_status.eq("no_data"), "ts_code"].nunique(), "passed": raw.loc[raw.source_status.eq("no_data"), "ts_code"].nunique() == 167},
        {"check": "duplicate_contract_date_keys", "value": int(normalized.duplicated(["ts_code", "date"]).sum()), "passed": not normalized.duplicated(["ts_code", "date"]).any()},
        {"check": "T_raw_2_to_decimal_002", "value": float(normalized.loc[normalized.instrument.eq("T"), "long_margin_rate_decimal"].median()), "passed": bool(np.isclose(normalized.loc[normalized.instrument.eq("T"), "long_margin_rate_decimal"].median(), 0.02))},
        {"check": "normalized_rate_range", "value": float(max(normalized.long_margin_rate_decimal.max(), normalized.short_margin_rate_decimal.max())), "passed": bool(((normalized.long_margin_rate_decimal.dropna() > 0) & (normalized.long_margin_rate_decimal.dropna() <= 0.5)).all() and ((normalized.short_margin_rate_decimal.dropna() > 0) & (normalized.short_margin_rate_decimal.dropna() <= 0.5)).all())},
        {"check": "both_direction_nonnull_rows", "value": int((normalized.long_margin_rate_decimal.notna() & normalized.short_margin_rate_decimal.notna()).sum()), "passed": True},
    ])
    return normalized, audit


@dataclass(frozen=True)
class MarginLookup:
    base_rate: float
    vendor_rate: float | None
    effective_rate: float
    rate_date: pd.Timestamp | None
    known_at: pd.Timestamp | None
    stale_trading_days: int | None
    source_code: str
    unit_rule_id: str | None
    vendor_binding: bool


class LaggedMarginTable:
    def __init__(self, normalized: pd.DataFrame, trading_dates, max_stale_trading_days: int = 5):
        self.maximum_stale = int(max_stale_trading_days)
        self.calendar = sorted(pd.Timestamp(x).normalize() for x in pd.to_datetime(pd.Index(trading_dates)).unique())
        self.calendar_index = {d: i for i, d in enumerate(self.calendar)}
        self.records: dict[str, pd.DataFrame] = {}
        for contract, group in normalized.groupby("ts_code", sort=False):
            self.records[str(contract)] = group.sort_values("date", kind="mergesort").reset_index(drop=True)

    def previous_trading_day(self, date) -> pd.Timestamp | None:
        d = pd.Timestamp(date).normalize()
        i = bisect_right(self.calendar, d) - 1
        if i >= 0 and self.calendar[i] == d:
            i -= 1
        return self.calendar[i] if i >= 0 else None

    def lookup(self, date, contract: str, quantity: int, fallback_rate: float) -> MarginLookup:
        cutoff = self.previous_trading_day(date)
        if cutoff is None or contract not in self.records:
            return MarginLookup(fallback_rate, None, fallback_rate, None, None, None, FALLBACK_SOURCE, None, False)
        group = self.records[contract]
        dates = list(pd.to_datetime(group["date"]))
        pos = bisect_right(dates, cutoff) - 1
        if pos < 0:
            return MarginLookup(fallback_rate, None, fallback_rate, None, None, None, FALLBACK_SOURCE, None, False)
        row = group.iloc[pos]
        rate_date = pd.Timestamp(row["date"]).normalize()
        cutoff_index = self.calendar_index.get(cutoff)
        rate_index = bisect_right(self.calendar, rate_date) - 1
        stale = None if cutoff_index is None or rate_index < 0 else cutoff_index - rate_index
        field = "long_margin_rate_decimal" if quantity > 0 else "short_margin_rate_decimal"
        vendor = row.get(field, np.nan)
        if stale is None or stale > self.maximum_stale or not np.isfinite(vendor):
            return MarginLookup(fallback_rate, None, fallback_rate, rate_date, pd.Timestamp(row["known_at"]), stale, FALLBACK_SOURCE, str(row["unit_rule_id"]), False)
        vendor = float(vendor)
        effective = max(float(fallback_rate), vendor)
        return MarginLookup(float(fallback_rate), vendor, effective, rate_date, pd.Timestamp(row["known_at"]), stale, VENDOR_SOURCE, str(row["unit_rule_id"]), vendor > float(fallback_rate))
