from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


SCHEMAS: dict[str, list[str]] = {
    "registry_static_validation": ["check_id", "expected", "actual", "passed", "detail"],
    "expected_artifact_inventory": ["baseline", "scenario", "artifact", "path", "requirement", "exists", "status", "rows", "sha256", "note"],
    "limit_endpoint_probe": ["exchange", "contract_role", "ts_code", "instrument", "query_start", "query_end", "classification", "row_count", "error_class", "error_fingerprint", "content_hash"],
    "margin_coverage_probe": ["scope", "instrument", "year", "position_rows", "official_rows", "vendor_daily_rows", "official_or_derived_rate", "vendor_daily_rate", "threshold", "passed", "status", "note"],
    "margin_endpoint_probe": ["ts_code", "instrument", "exchange", "query_start", "query_end", "classification", "row_count", "usable_rate_rows", "error_class", "error_fingerprint", "content_hash"],
    "next_open_validation": ["instrument", "ts_code", "trade_date", "daily_open", "minute_first_time", "minute_first_open", "session", "classification", "matched", "error_class", "error_fingerprint"],
    "test_results": ["suite", "test", "status", "duration_seconds", "detail"],
    "modified_files": ["path", "change_type", "sha256"],
    "plan_hashes": ["path", "sha256", "bytes"],
    "probe_errors": ["probe", "key", "classification", "error_class", "error_fingerprint"],
}


def empty_table(name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=SCHEMAS[name])


def ensure_schema(name: str, records: Iterable[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(list(records))
    for column in SCHEMAS[name]:
        if column not in frame:
            frame[column] = pd.Series(dtype="object")
    return frame.reindex(columns=SCHEMAS[name])
