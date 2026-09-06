from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .canonical import canonical_dataframe_hash
from .schemas import ensure_schema


EXCHANGE_SUFFIX = {"SHFE": "SHF", "INE": "INE", "DCE": "DCE", "CZCE": "ZCE", "CFFEX": "CFX"}
PROBE_ROOTS = {"SHFE": "RB", "INE": "SC", "DCE": "M", "CZCE": "TA", "CFFEX": "T"}


def sanitize_error(exc: Exception) -> tuple[str, str, str]:
    text = re.sub(r"[A-Za-z0-9_-]{24,}", "[REDACTED]", str(exc))
    lowered = text.lower()
    if any(term in lowered for term in ("权限", "permission", "积分不足", "no privilege")):
        classification = "NO_PERMISSION"
    elif any(term in lowered for term in ("timeout", "timed out", "connection", "network", "dns")):
        classification = "ENDPOINT_UNAVAILABLE"
    else:
        classification = "ENDPOINT_ERROR"
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return classification, type(exc).__name__, fingerprint


def select_limit_contracts(fut_basic: pd.DataFrame, as_of: str = "2026-08-31") -> pd.DataFrame:
    rows: list[dict] = []
    date_key = as_of.replace("-", "")
    for exchange, root in PROBE_ROOTS.items():
        subset = fut_basic[(fut_basic["exchange"] == exchange) & (fut_basic["fut_code"].astype(str).str.upper() == root)].copy()
        subset["list_date"] = subset["list_date"].astype(str)
        subset["delist_date"] = subset["delist_date"].astype(str)
        historical = subset[subset["delist_date"] < date_key].sort_values(["delist_date", "ts_code"])
        active = subset[(subset["list_date"] <= date_key) & (subset["delist_date"] >= date_key)].sort_values(["delist_date", "ts_code"])
        if historical.empty:
            historical = subset.sort_values(["delist_date", "ts_code"])
        if active.empty:
            active = subset.sort_values(["delist_date", "ts_code"], ascending=[False, True])
        for role, frame in (("historical", historical.tail(1)), ("active", active.head(1))):
            if frame.empty:
                rows.append({"exchange": exchange, "contract_role": role, "ts_code": None, "instrument": root, "list_date": None, "delist_date": None})
            else:
                record = frame.iloc[0]
                rows.append({"exchange": exchange, "contract_role": role, "ts_code": record["ts_code"], "instrument": root, "list_date": record["list_date"], "delist_date": record["delist_date"]})
    return pd.DataFrame(rows)


def probe_ft_limit(pro: Any, contracts: pd.DataFrame, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    for row in contracts.to_dict("records"):
        start = str(row.get("list_date") or "20150101")
        end = str(row.get("delist_date") or "20260831")
        if row["contract_role"] == "historical":
            start = max(start, "20230101")
        else:
            start = max(start, "20260101")
            end = min(end, "20260831")
        base = {
            "exchange": row["exchange"], "contract_role": row["contract_role"], "ts_code": row["ts_code"],
            "instrument": row["instrument"], "query_start": start, "query_end": end,
        }
        try:
            if not row["ts_code"]:
                raise LookupError("no local contract candidate")
            frame = pro.ft_limit(ts_code=row["ts_code"], start_date=start, end_date=end)
            if frame is None or frame.empty:
                classification, error_class, fingerprint = "SILENT_EMPTY", "", ""
                count, content_hash = 0, None
            else:
                classification, error_class, fingerprint = "DATA", "", ""
                count = len(frame)
                content_hash = canonical_dataframe_hash(frame, sort_by=[c for c in ("trade_date", "ts_code") if c in frame])
                frame.to_pickle(raw_dir / f"ft_limit_{row['exchange']}_{row['contract_role']}.pkl")
            records.append({**base, "classification": classification, "row_count": count, "error_class": error_class, "error_fingerprint": fingerprint, "content_hash": content_hash})
        except Exception as exc:
            classification, error_class, fingerprint = sanitize_error(exc)
            records.append({**base, "classification": classification, "row_count": 0, "error_class": error_class, "error_fingerprint": fingerprint, "content_hash": None})
            errors.append({"probe": "ft_limit", "key": f"{row['exchange']}:{row['contract_role']}", "classification": classification, "error_class": error_class, "error_fingerprint": fingerprint})
    return ensure_schema("limit_endpoint_probe", records), ensure_schema("probe_errors", errors)


def margin_coverage_from_cache(project_root: Path, fresh_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    raw_path = project_root / "data/v3/fees/tushare_fut_settle_daily_raw.pkl"
    bars = pd.read_pickle(project_root / "data/normalized_v2/bars.pkl")
    raw = pd.read_pickle(raw_path) if raw_path.exists() else pd.DataFrame()
    if fresh_raw is not None and not fresh_raw.empty:
        raw = pd.concat([raw, fresh_raw], ignore_index=True, sort=False)
        key_columns = [c for c in ("ts_code", "trade_date") if c in raw]
        if key_columns:
            raw = raw.drop_duplicates(key_columns, keep="last")
    position_frames = []
    for relative in (
        "outputs/v3_20260902_001129/00_formal__formal_baseline/positions.pkl",
        "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/positions.pkl",
    ):
        path = project_root / relative
        if path.exists():
            part = pd.read_pickle(path)
            part["baseline"] = "v3" if "v3_" in relative else "v4_2_S1"
            position_frames.append(part)
    positions = pd.concat(position_frames, ignore_index=True)
    positions["date"] = pd.to_datetime(positions["date"])
    positions = positions[(positions["date"].dt.year.between(2015, 2020)) & (positions["position"] != 0)].copy()
    positions["year"] = positions["date"].dt.year
    positions["exchange"] = positions["contract"].astype(str).str.split(".").str[-1]
    rate_keys: set[tuple[str, pd.Timestamp]] = set()
    if not raw.empty:
        temp = raw.copy()
        temp["trade_date"] = pd.to_datetime(temp["trade_date"].astype(str))
        rate_cols = [c for c in ("long_margin_rate", "short_margin_rate", "b_hedging_margin_rate", "s_hedging_margin_rate") if c in temp]
        usable = temp[rate_cols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
        rate_keys = set(zip(temp.loc[usable, "ts_code"].astype(str), temp.loc[usable, "trade_date"]))
    positions["vendor_daily"] = [(str(c), d) in rate_keys for c, d in zip(positions["contract"], positions["date"])]
    # Vendor data is intentionally not relabelled as official exchange evidence.
    positions["official_or_derived"] = False
    records: list[dict] = []
    for (baseline, instrument, year), group in positions.groupby(["baseline", "instrument", "year"], dropna=False):
        vendor = int(group["vendor_daily"].sum())
        official = int(group["official_or_derived"].sum())
        total = len(group)
        records.append({"scope": baseline, "instrument": instrument, "year": int(year), "position_rows": total, "official_rows": official, "vendor_daily_rows": vendor, "official_or_derived_rate": official / total if total else np.nan, "vendor_daily_rate": vendor / total if total else np.nan, "threshold": 0.80, "passed": official / total >= 0.80 if total else False, "status": "UNVERIFIED_VENDOR_NOT_OFFICIAL", "note": "Tushare fut_settle cache measured separately; no primary-source validation/effective-date derivation present"})
    for scope, group in positions.groupby("baseline"):
        total, vendor, official = len(group), int(group.vendor_daily.sum()), int(group.official_or_derived.sum())
        records.append({"scope": scope, "instrument": "ALL", "year": "2015-2020", "position_rows": total, "official_rows": official, "vendor_daily_rows": vendor, "official_or_derived_rate": official / total if total else np.nan, "vendor_daily_rate": vendor / total if total else np.nan, "threshold": 0.95, "passed": official / total >= 0.95 if total else False, "status": "UNVERIFIED_VENDOR_NOT_OFFICIAL", "note": "formal G5 threshold applies to official or causally derived rules"})
    return ensure_schema("margin_coverage_probe", records)


def probe_margin_endpoint(pro: Any, project_root: Path, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for relative in (
        "outputs/v3_20260902_001129/00_formal__formal_baseline/positions.pkl",
        "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/positions.pkl",
    ):
        part = pd.read_pickle(project_root / relative)
        frames.append(part.rename(columns={"contract": "ts_code"})[["ts_code", "instrument", "date", "position"]])
    exposed = pd.concat(frames, ignore_index=True)
    exposed["date"] = pd.to_datetime(exposed["date"])
    exposed = exposed[(exposed.date.dt.year.between(2015, 2020)) & (exposed.position != 0)]
    exposed["exchange"] = exposed.ts_code.astype(str).str.split(".").str[-1]
    records, errors, raw_frames = [], [], []
    for (ts_code, instrument, exchange), group in exposed[exposed.exchange.isin(["SHF", "INE"])].groupby(["ts_code", "instrument", "exchange"]):
        start = group.date.min().strftime("%Y%m%d")
        end = group.date.max().strftime("%Y%m%d")
        base = {"ts_code": ts_code, "instrument": instrument, "exchange": exchange, "query_start": start, "query_end": end}
        try:
            frame = pro.fut_settle(ts_code=ts_code, start_date=start, end_date=end)
            if frame is None or frame.empty:
                records.append({**base, "classification": "SILENT_EMPTY", "row_count": 0, "usable_rate_rows": 0, "error_class": "", "error_fingerprint": "", "content_hash": None})
                continue
            rate_cols = [c for c in ("long_margin_rate", "short_margin_rate", "b_hedging_margin_rate", "s_hedging_margin_rate") if c in frame]
            usable = int(frame[rate_cols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1).sum()) if rate_cols else 0
            content_hash = canonical_dataframe_hash(frame, sort_by=[c for c in ("trade_date", "ts_code") if c in frame])
            records.append({**base, "classification": "DATA", "row_count": len(frame), "usable_rate_rows": usable, "error_class": "", "error_fingerprint": "", "content_hash": content_hash})
            frame = frame.copy()
            frame["requested_ts_code"] = ts_code
            raw_frames.append(frame)
        except Exception as exc:
            classification, error_class, fingerprint = sanitize_error(exc)
            records.append({**base, "classification": classification, "row_count": 0, "usable_rate_rows": 0, "error_class": error_class, "error_fingerprint": fingerprint, "content_hash": None})
            errors.append({"probe": "fut_settle", "key": ts_code, "classification": classification, "error_class": error_class, "error_fingerprint": fingerprint})
    raw = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    if not raw.empty:
        raw.to_pickle(raw_dir / "fut_settle_2015_2020_shfe_ine_probe.pkl")
    return ensure_schema("margin_endpoint_probe", records), raw, ensure_schema("probe_errors", errors)


def select_next_open_samples(project_root: Path, seed: int = 20260905) -> pd.DataFrame:
    fills = pd.read_pickle(project_root / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")
    bars = pd.read_pickle(project_root / "data/normalized_v2/bars.pkl")
    fills = fills.rename(columns={"contract": "ts_code"})[["instrument", "ts_code", "date", "open_price"]].drop_duplicates()
    bars_sample = bars.rename(columns={"open": "open_price"})[["instrument", "ts_code", "date", "open_price"]].drop_duplicates()
    rng = np.random.default_rng(seed)
    output = []
    for instrument in ("RB", "SC", "M", "TA", "T"):
        source = fills[fills.instrument == instrument].copy()
        if len(source) < 15:
            source = bars_sample[bars_sample.instrument == instrument].copy()
        source["date"] = pd.to_datetime(source["date"])
        source = source[(source.date >= "2015-01-01") & (source.date <= "2026-08-31")].sort_values(["date", "ts_code"])
        indices = np.sort(rng.choice(len(source), size=15, replace=False))
        output.append(source.iloc[indices])
    return pd.concat(output, ignore_index=True)


def _minute_call(pro: Any, ts_code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    for kwargs in (
        {"ts_code": ts_code, "freq": "1min", "start_date": start.strftime("%Y-%m-%d %H:%M:%S"), "end_date": end.strftime("%Y-%m-%d %H:%M:%S")},
        {"ts_code": ts_code, "freq": "1min", "start_date": start.strftime("%Y%m%d%H%M%S"), "end_date": end.strftime("%Y%m%d%H%M%S")},
    ):
        try:
            return pro.ft_mins(**kwargs)
        except TypeError:
            continue
    return pro.ft_mins(ts_code=ts_code, freq="1min", start_date=start.strftime("%Y-%m-%d %H:%M:%S"), end_date=end.strftime("%Y-%m-%d %H:%M:%S"))


def probe_next_open(pro: Any, samples: pd.DataFrame, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    for idx, row in samples.iterrows():
        trade_date = pd.Timestamp(row["date"])
        start = trade_date - timedelta(days=3)
        start = start.replace(hour=20, minute=0)
        end = trade_date.replace(hour=16, minute=0)
        base = {"instrument": row["instrument"], "ts_code": row["ts_code"], "trade_date": trade_date.date().isoformat(), "daily_open": float(row["open_price"])}
        try:
            minutes = _minute_call(pro, row["ts_code"], start, end)
            if minutes is None or minutes.empty:
                records.append({**base, "minute_first_time": None, "minute_first_open": None, "session": None, "classification": "SILENT_EMPTY", "matched": False, "error_class": "", "error_fingerprint": ""})
                continue
            time_col = next((c for c in ("trade_time", "datetime", "trade_date") if c in minutes), None)
            if time_col is None or "open" not in minutes:
                raise ValueError("minute response lacks time/open fields")
            minutes = minutes.copy()
            minutes[time_col] = pd.to_datetime(minutes[time_col])
            first = minutes.sort_values(time_col).iloc[0]
            first_time = pd.Timestamp(first[time_col])
            first_open = float(first["open"])
            session = "NIGHT_FIRST_SESSION" if first_time.hour >= 20 else "DAY_FIRST_SESSION"
            matched = bool(np.isclose(first_open, float(row["open_price"]), rtol=0, atol=1e-9))
            records.append({**base, "minute_first_time": first_time.isoformat(), "minute_first_open": first_open, "session": session, "classification": "DATA", "matched": matched, "error_class": "", "error_fingerprint": ""})
            minutes.to_pickle(raw_dir / f"ft_mins_{row['instrument']}_{idx:03d}.pkl")
        except Exception as exc:
            classification, error_class, fingerprint = sanitize_error(exc)
            records.append({**base, "minute_first_time": None, "minute_first_open": None, "session": None, "classification": classification, "matched": False, "error_class": error_class, "error_fingerprint": fingerprint})
            errors.append({"probe": "next_open", "key": f"{row['instrument']}:{row['ts_code']}:{trade_date.date()}", "classification": classification, "error_class": error_class, "error_fingerprint": fingerprint})
    return ensure_schema("next_open_validation", records), ensure_schema("probe_errors", errors)
