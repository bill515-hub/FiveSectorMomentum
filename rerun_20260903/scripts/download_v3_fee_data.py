from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

import pandas as pd
import tushare as ts

from five_sector_momentum.data_source import load_local_env
from five_sector_momentum.storage import read_frame, write_frame


FIELDS = (
    "ts_code,trade_date,settle,trading_fee_rate,trading_fee,offset_today_fee,"
    "delivery_fee,b_hedging_margin_rate,s_hedging_margin_rate,long_margin_rate,"
    "short_margin_rate,exchange"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", default="data/normalized_v2/mapping")
    parser.add_argument("--output", default="data/v3/fees")
    parser.add_argument("--pause", type=float, default=0.05)
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    load_local_env(project)
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not available")
    output = (project / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    mapping = read_frame(project / args.mapping)
    windows = (
        mapping.groupby(["contract", "instrument"], as_index=False)
        .agg(start_date=("date", "min"), end_date=("date", "max"))
        .sort_values(["instrument", "contract"])
        .reset_index(drop=True)
    )
    cache_base = output / "tushare_fut_settle_daily_raw"
    try:
        cached = read_frame(cache_base)
    except FileNotFoundError:
        cached = pd.DataFrame()
    completed = set(cached["requested_contract"].dropna().astype(str)) if not cached.empty else set()
    failure_path = output / "download_failures.csv"
    failures = pd.read_csv(failure_path) if failure_path.exists() else pd.DataFrame()
    failed_contracts = set(failures.get("contract", pd.Series(dtype=str)).astype(str))
    pro = ts.pro_api(token)
    new_frames: list[pd.DataFrame] = []
    new_failures: list[dict[str, str]] = []
    total = len(windows)
    for index, row in windows.iterrows():
        contract = str(row["contract"])
        if contract in completed:
            continue
        try:
            frame = pro.fut_settle(
                ts_code=contract,
                start_date=pd.Timestamp(row["start_date"]).strftime("%Y%m%d"),
                end_date=pd.Timestamp(row["end_date"]).strftime("%Y%m%d"),
                fields=FIELDS,
            )
            if frame is None:
                frame = pd.DataFrame()
            if frame.empty:
                # Preserve an explicit no-data marker so resume does not silently
                # retry it and coverage can distinguish unavailable contracts.
                frame = pd.DataFrame([{
                    "ts_code": contract, "trade_date": pd.NaT,
                    "requested_contract": contract, "instrument": row["instrument"],
                    "source_status": "no_data",
                }])
            else:
                frame = frame.copy()
                frame["requested_contract"] = contract
                frame["instrument"] = row["instrument"]
                frame["source_status"] = "tushare"
            new_frames.append(frame)
            completed.add(contract)
            failed_contracts.discard(contract)
        except Exception as exc:
            new_failures.append({
                "contract": contract, "instrument": str(row["instrument"]),
                "error_type": type(exc).__name__, "error": str(exc)[:500],
            })
        if (len(new_frames) + len(new_failures)) % 25 == 0:
            cached = pd.concat([cached, *new_frames], ignore_index=True) if new_frames else cached
            new_frames.clear()
            write_frame(cached, cache_base)
            if new_failures:
                failures = pd.concat([failures, pd.DataFrame(new_failures)], ignore_index=True)
                new_failures.clear()
                failures.drop_duplicates("contract", keep="last").to_csv(
                    failure_path, index=False, encoding="utf-8-sig"
                )
            print(f"progress {len(completed)}/{total}, failures {len(failed_contracts)}", flush=True)
        time.sleep(args.pause)

    cached = pd.concat([cached, *new_frames], ignore_index=True) if new_frames else cached
    cached = cached.drop_duplicates(["requested_contract", "trade_date"], keep="last")
    write_frame(cached, cache_base)
    if new_failures:
        failures = pd.concat([failures, pd.DataFrame(new_failures)], ignore_index=True)
    if not failures.empty:
        failures.drop_duplicates("contract", keep="last").to_csv(
            failure_path, index=False, encoding="utf-8-sig"
        )
    usable = cached[cached["source_status"].eq("tushare")].copy()
    usable["trade_date"] = pd.to_datetime(usable["trade_date"])
    mapped = mapping.merge(
        usable,
        left_on=["date", "contract"], right_on=["trade_date", "requested_contract"],
        how="left", suffixes=("_mapping", "_fee"),
    )
    coverage = (
        mapped.assign(has_fee=mapped["source_status"].eq("tushare"))
        .groupby("instrument_mapping", as_index=False)
        .agg(mapping_days=("date", "size"), tushare_fee_days=("has_fee", "sum"))
    )
    coverage["coverage_ratio"] = coverage["tushare_fee_days"] / coverage["mapping_days"]
    coverage.to_csv(output / "tushare_fee_coverage.csv", index=False, encoding="utf-8-sig")
    print(coverage.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
