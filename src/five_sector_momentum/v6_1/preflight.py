from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts

from .canonical import file_hash, table_hash, write_pair
from .probe_errors import call_with_evidence
from .secrets import scan


ROOT = Path(__file__).resolve().parents[3]
OLD_PROBE = ROOT / "outputs/v6_20260906_135321_phase0_1a"
POSITIONS = {
    "v3_formal": ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/positions.pkl",
    "v4_2_S1": ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/positions.pkl",
}
MARGIN_FIELDS = ["long_margin_rate", "short_margin_rate", "b_hedging_margin_rate", "s_hedging_margin_rate"]


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _client():
    env = ROOT / ".env"
    if env.exists() and not os.getenv("TUSHARE_TOKEN"):
        for raw in env.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip().startswith("TUSHARE_TOKEN="):
                os.environ["TUSHARE_TOKEN"] = raw.split("=", 1)[1].strip().strip("'\"")
                break
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("secure Tushare credential is unavailable")
    return ts.pro_api(token)


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _listing_map() -> pd.DataFrame:
    basic = pd.read_pickle(ROOT / "data/raw/tushare/fut_basic.pkl").copy()
    basic["list_date"] = pd.to_datetime(basic.list_date, errors="coerce")
    basic["delist_date"] = pd.to_datetime(basic.delist_date, errors="coerce")
    return basic.sort_values(["ts_code", "list_date"]).drop_duplicates("ts_code", keep="last")


def _exposure_contracts() -> pd.DataFrame:
    frames = []
    for baseline, path in POSITIONS.items():
        frame = pd.read_pickle(path)
        frame["date"] = pd.to_datetime(frame.date)
        frame = frame[(frame.position != 0) & frame.date.between("2015-01-01", "2020-12-31")]
        frame = frame[frame.contract.str.endswith((".SHF", ".INE"), na=False)]
        grouped = frame.groupby(["contract", "instrument"], as_index=False).agg(first_exposure=("date", "min"), last_exposure=("date", "max"), position_days=("date", "nunique"))
        grouped["baseline"] = baseline
        frames.append(grouped)
    all_rows = pd.concat(frames, ignore_index=True)
    return all_rows.sort_values(["baseline", "contract"]).reset_index(drop=True)


def _probe(pro: Any, api: str, key: str, callback) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    return call_with_evidence(api, key, callback)


def _margin_coverage(fresh: pd.DataFrame, exposures: pd.DataFrame) -> pd.DataFrame:
    cached = pd.read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl").copy()
    available = pd.concat([cached, fresh], ignore_index=True, sort=False)
    if available.empty:
        available = pd.DataFrame(columns=["requested_contract", "ts_code", "trade_date", *MARGIN_FIELDS])
    available["contract_key"] = available.get("requested_contract", available.get("ts_code")).fillna(available.get("ts_code"))
    available["date_key"] = pd.to_datetime(available.trade_date, errors="coerce")
    for col in MARGIN_FIELDS:
        if col not in available:
            available[col] = pd.NA
    available["has_vendor_rate"] = available[MARGIN_FIELDS].notna().any(axis=1)
    usable = set(map(tuple, available.loc[available.has_vendor_rate, ["contract_key", "date_key"]].dropna().itertuples(index=False, name=None)))
    detail, summaries = [], []
    for baseline, path in POSITIONS.items():
        pos = pd.read_pickle(path).copy()
        pos["date"] = pd.to_datetime(pos.date)
        pos = pos[(pos.position != 0) & pos.date.between("2015-01-01", "2020-12-31")]
        pos = pos[pos.contract.str.endswith((".SHF", ".INE"), na=False)].drop_duplicates(["date", "contract"])
        pos["has_vendor_rate"] = [(c, d) in usable for c, d in zip(pos.contract, pos.date)]
        pos["baseline"] = baseline
        pos["year"] = pos.date.dt.year
        detail.append(pos[["baseline", "date", "contract", "instrument", "position", "has_vendor_rate"]])
        for keys, g in pos.groupby(["instrument", "year"]):
            summaries.append({"baseline": baseline, "instrument": keys[0], "year": keys[1], "position_days": len(g), "vendor_rate_days": int(g.has_vendor_rate.sum()), "vendor_coverage": float(g.has_vendor_rate.mean()), "fallback_share": float(1-g.has_vendor_rate.mean()), "source_label": "VENDOR_DAILY_UNVERIFIED_OR_STATIC_FALLBACK_PROXY"})
        summaries.append({"baseline": baseline, "instrument": "ALL", "year": "ALL", "position_days": len(pos), "vendor_rate_days": int(pos.has_vendor_rate.sum()), "vendor_coverage": float(pos.has_vendor_rate.mean()) if len(pos) else None, "fallback_share": float(1-pos.has_vendor_rate.mean()) if len(pos) else None, "source_label": "VENDOR_DAILY_UNVERIFIED_OR_STATIC_FALLBACK_PROXY"})
    return pd.DataFrame(summaries), pd.concat(detail, ignore_index=True)


def _recent_session_probe(basic: pd.DataFrame) -> pd.DataFrame:
    rows = []
    try:
        import akshare as ak
    except Exception as exc:
        return pd.DataFrame([{"instrument": x, "classification": "NOT_TESTABLE", "observations": 0, "matched": 0, "match_rate": None, "safe_message_code": "AKSHARE_IMPORT_UNAVAILABLE", "exception_class": exc.__class__.__name__} for x in ["RB", "SC", "M", "TA", "T"]])
    bars = pd.read_pickle(ROOT / "data/normalized_v2/bars.pkl")
    bars["date"] = pd.to_datetime(bars.date)
    for instrument in ["RB", "SC", "M", "TA", "T"]:
        subset = basic[(basic.fut_code == instrument) & (basic.list_date <= pd.Timestamp("2026-08-31")) & (basic.delist_date >= pd.Timestamp("2026-08-01"))]
        if subset.empty:
            rows.append({"instrument": instrument, "classification": "NOT_TESTABLE", "observations": 0, "matched": 0, "match_rate": None, "safe_message_code": "NO_RECENT_CONTRACT", "exception_class": ""})
            continue
        contract = subset.sort_values("delist_date").iloc[-1].ts_code
        symbol = contract.split(".")[0]
        try:
            minute = ak.futures_zh_minute_sina(symbol=symbol, period="1")
            if minute is None or minute.empty:
                raise ValueError("empty minute response")
            minute = minute.copy()
            time_col = next((c for c in minute.columns if str(c).lower() in {"datetime", "时间", "date"}), minute.columns[0])
            open_col = next((c for c in minute.columns if str(c).lower() in {"open", "开盘"}), None)
            if open_col is None:
                raise ValueError("open column unavailable")
            minute["dt"] = pd.to_datetime(minute[time_col], errors="coerce")
            minute["trade_date"] = minute.dt.dt.normalize()
            first = minute.dropna(subset=["dt"]).sort_values("dt").groupby("trade_date", as_index=False).first().tail(15)
            daily = bars[bars.ts_code.eq(contract)][["date", "open"]].rename(columns={"date": "trade_date", "open": "daily_open"})
            merged = first.merge(daily, on="trade_date", how="inner")
            matched = int(pd.to_numeric(merged[open_col], errors="coerce").eq(pd.to_numeric(merged.daily_open, errors="coerce")).sum())
            n = len(merged)
            rows.append({"instrument": instrument, "ts_code": contract, "classification": "RECENT_SESSION_CONVENTION_PARTIALLY_VERIFIED" if n else "NOT_TESTABLE", "observations": n, "matched": matched, "match_rate": matched/n if n else None, "safe_message_code": "RECENT_ONLY_NOT_HISTORICAL", "exception_class": ""})
        except Exception as exc:
            rows.append({"instrument": instrument, "ts_code": contract, "classification": "NOT_TESTABLE", "observations": 0, "matched": 0, "match_rate": None, "safe_message_code": "RECENT_MINUTE_DATA_UNAVAILABLE", "exception_class": exc.__class__.__name__})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = (args.output_dir or ROOT / f"outputs/v6_1_{stamp}_preflight").resolve()
    out.mkdir(parents=True, exist_ok=False)
    raw = ROOT / "data/v6_1/raw" / out.name
    raw.mkdir(parents=True, exist_ok=True)
    tables: dict[str, Any] = {}
    pro = _client()

    control, control_state, attempt_rows = _probe(pro, "trade_cal", "SSE_202601", lambda: pro.trade_cal(exchange="SSE", start_date="20260101", end_date="20260110"))
    control_frame = pd.DataFrame([{"classification": control_state, "row_count": len(control), "positive_control": True}])
    tables["connectivity_control"] = write_pair(control_frame, out / "connectivity_control")
    if control_state in {"NETWORK_BLOCKED", "NETWORK_ERROR", "RATE_LIMITED"}:
        attempts = pd.DataFrame(attempt_rows)
        tables["endpoint_attempt_log"] = write_pair(attempts, out / "endpoint_attempt_log")
        status = {"status": "BLOCKED_PREFLIGHT_NETWORK_EVIDENCE", "performance_generated": False, "registry_frozen": False, "generated_at": datetime.now().isoformat()}
        _json(out / "V6_1_PREFLIGHT_STATUS.json", status)
        (out / "V6_1_PREFLIGHT_EVIDENCE_REPORT.md").write_text("# v6.1 数据预检证据报告\n\n状态：**BLOCKED_PREFLIGHT_NETWORK_EVIDENCE**。基础连通性正控制未通过；未冻结注册表，未生成绩效。\n", encoding="utf-8")
        print(json.dumps({"status": status["status"], "output_dir": str(out)}, ensure_ascii=False))
        return 3

    limit_contracts = pd.read_pickle(OLD_PROBE / "limit_probe_contracts.pkl")
    limit_rows = []
    for row in limit_contracts.itertuples():
        frame, state, attempts = _probe(pro, "ft_limit", row.ts_code, lambda code=row.ts_code: pro.ft_limit(ts_code=code))
        attempt_rows.extend(attempts)
        limit_rows.append({"exchange": row.exchange, "contract_role": row.contract_role, "ts_code": row.ts_code, "classification": state, "row_count": len(frame), "content_sha256": table_hash(frame) if len(frame) else None})
        if len(frame):
            write_pair(frame, raw / f"ft_limit_{row.ts_code.replace('.', '_')}")
    limits = pd.DataFrame(limit_rows)
    tables["ft_limit_probe_corrected"] = write_pair(limits, out / "ft_limit_probe_corrected")

    samples = pd.read_pickle(OLD_PROBE / "next_open_samples.pkl")
    minute_rows = []
    for instrument, group in samples.groupby("instrument", sort=True):
        sample = group.iloc[-1]
        start = _date_text(pd.Timestamp(sample.date) - pd.Timedelta(days=2)) + " 00:00:00"
        end = _date_text(pd.Timestamp(sample.date) + pd.Timedelta(days=2)) + " 23:59:59"
        frame, state, attempts = _probe(pro, "ft_mins", sample.ts_code, lambda code=sample.ts_code, s=start, e=end: pro.ft_mins(ts_code=code, freq="1min", start_date=s, end_date=e))
        attempt_rows.extend(attempts)
        minute_rows.append({"instrument": instrument, "ts_code": sample.ts_code, "classification": state, "row_count": len(frame)})
    minute_probe = pd.DataFrame(minute_rows)
    tables["ft_mins_probe_corrected"] = write_pair(minute_probe, out / "ft_mins_probe_corrected")
    historical_validation = samples.copy().rename(columns={"date": "trade_date", "open_price": "daily_open"})
    historical_validation["minute_observations"] = 0
    historical_validation["classification"] = "NOT_TESTABLE"
    historical_validation["match_rate"] = pd.NA
    tables["next_open_historical_validation_status"] = write_pair(historical_validation, out / "next_open_historical_validation_status")

    basic = _listing_map()
    exposures = _exposure_contracts()
    queries = pd.concat([
        pd.DataFrame([{"contract": "RB2410.SHF", "instrument": "RB", "first_exposure": "2024-01-01", "last_exposure": "2024-10-15", "baseline": "POSITIVE_CONTROL"}, {"contract": "T2403.CFX", "instrument": "T", "first_exposure": "2023-01-01", "last_exposure": "2024-03-15", "baseline": "POSITIVE_CONTROL"}]),
        exposures,
    ], ignore_index=True).drop_duplicates(["contract", "first_exposure", "last_exposure"])
    fresh_frames, margin_rows = [], []
    positive_ok = False
    for row in queries.itertuples():
        start, end = _date_text(row.first_exposure), _date_text(row.last_exposure)
        frame, state, attempts = _probe(pro, "fut_settle", row.contract, lambda code=row.contract, s=start, e=end: pro.fut_settle(ts_code=code, start_date=s, end_date=e))
        attempt_rows.extend(attempts)
        if row.baseline == "POSITIVE_CONTROL" and state == "DATA":
            positive_ok = True
        final_state = "KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL" if state == "SILENT_EMPTY" and positive_ok and row.baseline != "POSITIVE_CONTROL" else state
        margin_rows.append({"baseline": row.baseline, "ts_code": row.contract, "instrument": row.instrument, "start_date": start, "end_date": end, "classification": final_state, "row_count": len(frame)})
        if len(frame):
            frame = frame.copy(); frame["requested_contract"] = row.contract; fresh_frames.append(frame)
            write_pair(frame, raw / f"fut_settle_{row.contract.replace('.', '_')}_{start}_{end}")
    margin_probe = pd.DataFrame(margin_rows)
    fresh = pd.concat(fresh_frames, ignore_index=True, sort=False) if fresh_frames else pd.DataFrame()
    summary, detail = _margin_coverage(fresh, exposures)
    tables["fut_settle_probe_corrected"] = write_pair(margin_probe, out / "fut_settle_probe_corrected")
    tables["margin_vendor_coverage_by_instrument_year"] = write_pair(summary, out / "margin_vendor_coverage_by_instrument_year")
    tables["margin_vendor_coverage_detail"] = write_pair(detail, out / "margin_vendor_coverage_detail")
    recent = _recent_session_probe(basic)
    tables["recent_session_convention_probe"] = write_pair(recent, out / "recent_session_convention_probe")
    attempts = pd.DataFrame(attempt_rows)
    tables["endpoint_attempt_log"] = write_pair(attempts, out / "endpoint_attempt_log")

    canonical_possible = len(limits) == 10 and limits.classification.eq("DATA").all()
    status_name = "V6_CANONICAL_DATA_NOW_POSSIBLE" if canonical_possible else "PREFLIGHT_EVIDENCE_READY_FOR_REGISTRY"
    status = {"status": status_name, "performance_generated": False, "registry_frozen": False, "ft_limit_classification": limits.classification.value_counts().to_dict(), "ft_mins_classification": minute_probe.classification.value_counts().to_dict(), "positive_controls": margin_probe[margin_probe.baseline.eq("POSITIVE_CONTROL")].to_dict("records"), "coverage_content_sha256": table_hash(summary), "generated_at": datetime.now().isoformat()}
    _json(out / "V6_1_PREFLIGHT_STATUS.json", status)
    report = f"""# v6.1 数据预检证据报告

状态：**{status_name}**。本阶段未冻结机器注册表、未生成任何绩效、未消耗完整历史 attempt。

## 结论

- 基础连通性正控制：`{control_state}`，返回 {len(control)} 行。
- `ft_limit`：{limits.classification.value_counts().to_dict()}。
- `ft_mins`：{minute_probe.classification.value_counts().to_dict()}；历史 75 点没有分钟观测时统一为 `NOT_TESTABLE`，不报告 0% 匹配。
- `fut_settle` 正控制和实际暴露合约结果见底层表。保证金仅标为 `VENDOR_DAILY_UNVERIFIED` 或 `STATIC_FALLBACK_PROXY`，不称官方历史保证金。
- AkShare/Sina 只作近期 session 约定诊断；无观测为 `NOT_TESTABLE`，有观测也不得外推至历史。

所有异常只保存层级、异常类、安全消息码、WinError/HTTP 状态与不可逆指纹，没有保存原始敏感请求或凭据。
"""
    report_name = "V6_CANONICAL_DATA_NOW_POSSIBLE.md" if canonical_possible else "V6_1_PREFLIGHT_EVIDENCE_REPORT.md"
    (out / report_name).write_text(report, encoding="utf-8")
    findings = scan([out, ROOT / "src/five_sector_momentum/v6_1"])
    write_pair(findings, out / "secret_scan_findings")
    manifest = {"status": status_name, "research_status": "PROVISIONAL_DAILY_ONLY", "tables": tables, "files": [{"path": str(p.resolve()), "sha256": file_hash(p)} for p in sorted(out.glob("*")) if p.is_file()], "secret_findings": len(findings)}
    _json(out / "manifest.json", manifest)
    print(json.dumps({"status": status_name, "output_dir": str(out), "secret_findings": len(findings)}, ensure_ascii=False))
    return 4 if canonical_possible else 0


if __name__ == "__main__":
    raise SystemExit(main())
