from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .canonical import file_hash, table_hash, write_pair
from .margin import LaggedMarginTable, normalize_margin_cache

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/v6_2"
V61 = ROOT / "outputs/v6_1_20260906_155224"

EXPECTED_HASHES = {
    ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml": "7128d97e69b5837469e8ebee4027a3668943c6c652a6332072f5fcabc923d591",
    V61 / "analysis/scenario_metrics.csv": "f4e68baf0142b5c9260d80b460a134ab6aac6096435398803a296864e37113ff",
    V61 / "analysis/accounting_reconciliation.csv": "9d8a4d750953a45e4605f4c06107f976027c6bbaded7109d9f5499cd82fb36b3",
    V61 / "analysis/rejections.csv": "cabb49328a0f635d0cfec549db2697c4486c5fe4ff2b3760407875c8150e2a1f",
}


def _coverage(table: LaggedMarginTable, frame: pd.DataFrame, quantity_column: str, label: str) -> pd.DataFrame:
    rows = []
    for rec in frame.itertuples(index=False):
        quantity = int(getattr(rec, quantity_column))
        if not quantity:
            continue
        instrument = str(rec.instrument)
        fallback = float(INSTRUMENT_META.loc[instrument, "fallback_margin_rate"])
        found = table.lookup(rec.date, str(rec.contract), quantity, fallback)
        rows.append({"scope": label, "date": pd.Timestamp(rec.date), "contract": rec.contract, "instrument": instrument, "quantity": quantity, "source_code": found.source_code, "vendor_available": found.vendor_rate is not None, "vendor_binding": found.vendor_binding, "stale_trading_days": found.stale_trading_days})
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame([{"scope": label, "rows": 0, "vendor_available_share": 0.0, "vendor_binding_share": 0.0, "fallback_share": 1.0}])
    return pd.DataFrame([{"scope": label, "rows": len(detail), "vendor_available_share": detail.vendor_available.mean(), "vendor_binding_share": detail.vendor_binding.mean(), "fallback_share": 1.0 - detail.vendor_available.mean()}])


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    hash_rows = [{"path": str(path.relative_to(ROOT)), "expected_sha256": expected, "actual_sha256": file_hash(path), "passed": file_hash(path) == expected} for path, expected in EXPECTED_HASHES.items()]
    hashes = pd.DataFrame(hash_rows)
    if not hashes.passed.all():
        raise AssertionError("V6_1_WHITELIST_HASH_MISMATCH")
    normalized, audit = normalize_margin_cache(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
    if not audit.passed.all():
        raise AssertionError("MARGIN_NORMALIZATION_AUDIT_FAILED")
    write_pair(hashes, DATA / "legacy_hash_verification")
    write_pair(normalized, DATA / "margin_normalized_rules")
    write_pair(audit, DATA / "margin_normalization_audit")

    locked = pd.read_csv(ROOT / "verify_20260903/tmp/locked_board_days.csv")
    locked["date"] = pd.to_datetime(locked["date"])
    locked = locked.assign(challenge_type="MAIN_CONTRACT_ONE_PRICE_OHLC_SHAPE", official_limit_truth=False, proxy_not_truth=True)
    ru = pd.DataFrame([{"date": pd.Timestamp("2025-04-07"), "instrument": "RU", "contract": "RU2505.SHF", "open": pd.NA, "high": pd.NA, "low": pd.NA, "close": pd.NA, "settle": pd.NA, "pre_settle": pd.NA, "vol": pd.NA, "challenge_type": "OLD_ROLL_LEG_ONE_PRICE_OHLC_SHAPE", "official_limit_truth": False, "proxy_not_truth": True}])
    challenge = pd.concat([locked, ru], ignore_index=True, sort=False).sort_values(["date", "contract"], kind="mergesort").reset_index(drop=True)
    challenge.insert(0, "challenge_id", [f"V62_CHALLENGE_{i:02d}" for i in range(1, len(challenge) + 1)])
    write_pair(challenge, DATA / "one_price_shape_challenge_set")

    global INSTRUMENT_META
    INSTRUMENT_META = pd.read_pickle(ROOT / "data/normalized_v2/instrument_meta.pkl").set_index("instrument")
    mapping = pd.read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
    table = LaggedMarginTable(normalized, mapping.date.unique(), 5)
    coverage = []
    for sid in ["P03", "P04"]:
        positions = pd.read_pickle(V61 / sid / "positions.pkl")
        targets = pd.read_pickle(V61 / sid / "targets.pkl")
        coverage.append(_coverage(table, positions, "position", f"{sid}_positions"))
        coverage.append(_coverage(table, targets, "optimal_position", f"{sid}_targets"))
    coverage_frame = pd.concat(coverage, ignore_index=True)
    write_pair(coverage_frame, DATA / "margin_preperformance_coverage")
    status = {
        "status": "PHASE_A_READY_FOR_REGISTRY_FREEZE",
        "performance_generated": False,
        "legacy_hashes_passed": True,
        "margin_unit_rules": {"T": "raw percentage points /100", "commodities": "raw decimal identity"},
        "normalized_margin_rows": len(normalized),
        "duplicate_keys": int(normalized.duplicated(["ts_code", "date"]).sum()),
        "challenge_rows": len(challenge),
        "normalized_margin_content_sha256": table_hash(normalized, ["ts_code", "date"]),
        "challenge_content_sha256": table_hash(challenge, ["date", "contract"]),
        "coverage_content_sha256": table_hash(coverage_frame, ["scope"]),
    }
    (DATA / "PHASE_A_STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

