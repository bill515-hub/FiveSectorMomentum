from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from five_sector_momentum.data_pipeline import build_panama_prices
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import price_diff_sharpe

from .canonical import file_hash, table_hash, write_pair
from .registry import load, validate


ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data/v6_3"
REGISTRY = ROOT / "docs/v6_3_three_horizon_and_single_window_plan/V6_3_MACHINE_REGISTRY.yaml"
CONFIG = ROOT / "configs/five_sector_momentum_v6_3.yaml"

EXPECTED_V62_HASHES = {
    "docs/v6_2_causal_daily_only_correction_plan/V6_2_MACHINE_REGISTRY.yaml": "5a728b6769e70761350c2cd73ae72b35acfef8251e9e4f9b5b2cc99dddc9edcc",
    "docs/v6_2_causal_daily_only_correction_plan/V6_2_REGISTRY_FREEZE.json": "4bb0c8be73504fb8c16733464329483efbf7f3df8058dbb085d6280d83ff40b8",
    "configs/five_sector_momentum_v6_2.yaml": "9f8f22c3a1c6566ee6c40b83bcf90ac4453a2b19f3f76d9cb06479377dde307f",
    "outputs/v6_2_20260906_222655/B03/daily_equity.pkl": "28a52e9470d85ca96a27e4068e6ed1eff6aee4b3fcc8f72119bbada1ca2f63e6",
    "outputs/v6_2_20260906_222655/B03/positions.pkl": "ff10ba9ed9a5d52ff8e9632a48caba1530f24281d884d8cc64b4077d62cc5719",
    "outputs/v6_2_20260906_222655/B03/targets.pkl": "1fa6346745740c7db3fdc8b619eb330e42802d23c85f4333ae1cf893f31118cd",
    "outputs/v6_2_20260906_222655/B03/orders.pkl": "f759ae08151cb38df6dad7823ba2d30a8b8d1c37d19e6cf07139b244a773d9c8",
    "outputs/v6_2_20260906_222655/B03/fills.pkl": "203d89559146d5e42f2c0347c8c0c9c675a53d1a0c4d22f958adbd08c7803269",
    "outputs/v6_2_20260906_222655/B03/pnl_by_instrument.pkl": "cd3cca6aa2eb22a1b417f9c88cc294e8ab81990a68ff4e8f84104f29d07ef177",
    "outputs/v6_2_20260906_222655/B03/accounting_reconciliation.pkl": "aade4230b8d35bb629ab2ed3e81c481f85371545eb39e13a403d7511c893ca11",
    "outputs/v6_2_20260906_222655/B04/daily_equity.pkl": "12289b8bed844b090ad0849871c1c9694b50d6bff89b26377ca197ca102d2270",
    "outputs/v6_2_20260906_222655/B04/positions.pkl": "2a084d33bfe38b9af325fceb1e0358744cdd3f4acf13b072781648f7a3b8f537",
    "outputs/v6_2_20260906_222655/B04/targets.pkl": "ed4108dac1f8e113eaf68c388cf60bd3cc5853e67ecd0eacd71fee29c5ce73eb",
    "outputs/v6_2_20260906_222655/B04/orders.pkl": "71a5b2e777347c62f49a5057837838d795a7a9e29eb11a78a87cf8270a4aa149",
    "outputs/v6_2_20260906_222655/B04/fills.pkl": "f0712819e45a4aac10c4230b8e0b60aecd203df4ff686390225576a95e812079",
    "outputs/v6_2_20260906_222655/B04/pnl_by_instrument.pkl": "9440bba412ea054def15b2e02e6af9e7bc4e2f9ed77e2adedabf2f8b465941f4",
    "outputs/v6_2_20260906_222655/B04/accounting_reconciliation.pkl": "c730e257ccf158ba5ff099a0899cd63d561438f35a2a86090e56d2c8d0dd0ac7",
}


def _gate(name: str, value: Any, expected: Any, passed: bool, severity: str = "HARD") -> dict[str, Any]:
    return {"check": name, "value": value, "expected": expected, "passed": bool(passed), "severity": severity}


def whitelist_inventory() -> pd.DataFrame:
    rows = []
    for relative, expected in EXPECTED_V62_HASHES.items():
        path = ROOT / relative
        actual = file_hash(path) if path.exists() else None
        rows.append({
            "path": relative, "artifact_class": "CORE_REPRODUCTION_EVIDENCE",
            "expected_sha256": expected, "actual_sha256": actual,
            "exists": path.exists(), "status": "PRESENT" if path.exists() else "MISSING",
            "passed": bool(path.exists() and actual == expected),
        })
    return pd.DataFrame(rows)


def data_contract_audit() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    bars = pd.read_pickle(ROOT / "data/normalized_v2/bars.pkl").copy()
    mapping = pd.read_pickle(ROOT / "data/normalized_v2/mapping.pkl").copy()
    adjusted = pd.read_pickle(ROOT / "data/normalized_v2/adjusted_prices.pkl").copy()
    bars["date"] = pd.to_datetime(bars["date"])
    mapping["date"] = pd.to_datetime(mapping["date"])
    adjusted["date"] = pd.to_datetime(adjusted["date"])

    complete = bars[["open", "high", "low", "close"]].notna().all(axis=1)
    ohlc_bad = complete & (
        bars["high"].lt(bars[["open", "close", "low"]].max(axis=1))
        | bars["low"].gt(bars[["open", "close", "high"]].min(axis=1))
    )
    nonpositive = pd.concat([
        bars.loc[bars[column].notna() & bars[column].le(0), ["date", "ts_code", "instrument"]].assign(field=column, value=bars.loc[bars[column].notna() & bars[column].le(0), column])
        for column in ["open", "high", "low", "close", "settlement"]
    ], ignore_index=True)
    mapped = mapping.merge(
        bars[["date", "ts_code", "open", "close", "settlement", "delist_date"]],
        left_on=["date", "contract"], right_on=["date", "ts_code"], how="left",
    )
    contract_expiry = bars[["ts_code", "delist_date"]].drop_duplicates("ts_code").set_index("ts_code")["delist_date"]
    ordered = mapping.sort_values(["instrument", "date"], kind="mergesort").copy()
    ordered["delist_date"] = ordered["contract"].map(contract_expiry)
    ordered["contract_change"] = ordered["contract"].ne(ordered.groupby("instrument")["contract"].shift())
    transitions = ordered.loc[ordered["contract_change"]].copy()
    transitions["previous_contract"] = transitions.groupby("instrument")["contract"].shift()
    transitions["previous_delist_date"] = transitions.groupby("instrument")["delist_date"].shift()
    backward = transitions.loc[
        transitions["previous_delist_date"].notna()
        & transitions["delist_date"].notna()
        & transitions["delist_date"].lt(transitions["previous_delist_date"])
    ].copy()

    mapped_missing = mapped.loc[mapped["ts_code"].isna()].copy()
    mapped_primary_missing = mapped.loc[mapped[["open", "close", "settlement"]].isna().any(axis=1)].copy()
    settlement_only_missing = mapped_primary_missing.loc[
        mapped_primary_missing["open"].notna() & mapped_primary_missing["close"].notna()
        & mapped_primary_missing["settlement"].isna()
    ].copy()
    mapped_after_delist = mapped.loc[mapped["delist_date"].notna() & mapped["date"].gt(mapped["delist_date"])].copy()

    rows = [
        _gate("bars_unique_date_contract", int(bars.duplicated(["date", "ts_code"]).sum()), 0, not bars.duplicated(["date", "ts_code"]).any()),
        _gate("mapping_unique_date_instrument", int(mapping.duplicated(["date", "instrument"]).sum()), 0, not mapping.duplicated(["date", "instrument"]).any()),
        _gate("adjusted_unique_date_instrument", int(adjusted.duplicated(["date", "instrument"]).sum()), 0, not adjusted.duplicated(["date", "instrument"]).any()),
        _gate("complete_ohlc_logic_violations", int(ohlc_bad.sum()), 0, not ohlc_bad.any()),
        _gate("nonpositive_trade_prices", len(nonpositive), 0, nonpositive.empty),
        _gate("mapped_contract_missing_bar", len(mapped_missing), 0, mapped_missing.empty),
        _gate("mapped_after_delist", len(mapped_after_delist), 0, mapped_after_delist.empty),
        _gate("mapping_dates_strictly_increasing", int(mapping.duplicated(["instrument", "date"]).sum()), 0, not mapping.duplicated(["instrument", "date"]).any()),
        _gate("mapped_contract_expiry_non_decreasing", len(backward), 0, backward.empty),
        _gate("mapped_open_or_close_missing", int((mapped["open"].isna() | mapped["close"].isna()).sum()), 0, not (mapped["open"].isna() | mapped["close"].isna()).any()),
        # Three known T settlement gaps fall back causally to close in the inherited engine.
        _gate("mapped_settlement_missing_disclosed", len(settlement_only_missing), 3, len(settlement_only_missing) == 3, "DISCLOSURE"),
    ]
    details = {
        "ohlc_logic_violations": bars.loc[ohlc_bad].copy(),
        "nonpositive_prices": nonpositive,
        "mapped_missing_bars": mapped_missing,
        "mapped_primary_missing": mapped_primary_missing,
        "mapped_after_delist": mapped_after_delist,
        "mapping_backward_expiry_transitions": backward,
        "mapping_contract_transitions": transitions,
    }
    return pd.DataFrame(rows), details


def panama_prefix_audit(cutoff: str = "2020-12-31") -> tuple[pd.DataFrame, pd.DataFrame]:
    settings = Settings.load(ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml")
    bars = pd.read_pickle(ROOT / "data/normalized_v2/bars.pkl")
    mapping = pd.read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
    cutoff_date = pd.Timestamp(cutoff)
    _, full_adjusted, _ = build_panama_prices(settings, bars, mapping)
    _, prefix_adjusted, _ = build_panama_prices(
        settings, bars.loc[bars.date.le(cutoff_date)].copy(),
        mapping.loc[mapping.date.le(cutoff_date)].copy(),
    )
    full_prices = full_adjusted.pivot(index="date", columns="instrument", values="adjusted_price").sort_index()
    prefix_prices = prefix_adjusted.pivot(index="date", columns="instrument", values="adjusted_price").sort_index()
    shared_index = prefix_prices.index.intersection(full_prices.index)
    shared_columns = prefix_prices.columns.intersection(full_prices.columns)
    full_diff = full_prices.loc[shared_index, shared_columns].diff()
    prefix_diff = prefix_prices.loc[shared_index, shared_columns].diff()
    delta = (full_diff - prefix_diff).abs()
    finite = delta.stack(dropna=True)
    rows = [{
        "check": "panama_price_difference_prefix_invariant", "cutoff": cutoff,
        "observations": len(finite), "max_abs_diff": float(finite.max()) if len(finite) else np.nan,
        "passed": bool(len(finite) and float(finite.max()) <= 1e-10),
    }]
    forecast_rows = []
    for horizon, skip in [(20, 0), (40, 0), (60, 0), (90, 0), (120, 0), (180, 0), (250, 0), (20, 5), (60, 5), (252, 0)]:
        left = price_diff_sharpe(prefix_diff, horizon, 252.0, skip)
        right = price_diff_sharpe(full_diff, horizon, 252.0, skip)
        signal_delta = (left - right).abs().stack(dropna=True)
        maximum = float(signal_delta.max()) if len(signal_delta) else 0.0
        forecast_rows.append({
            "window": horizon, "skip_recent_days": skip, "cutoff": cutoff,
            "observations": len(signal_delta), "max_abs_diff": maximum,
            "passed": maximum <= 1e-12,
        })
    return pd.DataFrame(rows), pd.DataFrame(forecast_rows)


def correlation_prior_audit() -> pd.DataFrame:
    registry = load(REGISTRY)
    prior = registry["correlation_selection_prior"]
    frame = pd.read_csv(ROOT / prior["source"])
    frame = frame.loc[
        frame["basis"].eq(prior["basis"]) & frame["phase"].eq(prior["phase"])
        & frame["method"].eq(prior["method"]) & frame["n"].eq(prior["n"])
    ]
    pairs = {
        "single_20_skip5__single_60": ("single_20_skip5", "single_60"),
        "single_60__single_250": ("single_60", "single_250"),
        "single_20_skip5__single_250": ("single_20_skip5", "single_250"),
        "single_120__single_250": ("single_120", "single_250"),
    }
    rows = []
    for key, (left, right) in pairs.items():
        found = frame.loc[
            (frame["left"].eq(left) & frame["right"].eq(right))
            | (frame["left"].eq(right) & frame["right"].eq(left))
        ]
        actual = float(found.iloc[0]["correlation"]) if len(found) == 1 else np.nan
        expected = float(prior["values"][key])
        rows.append({
            "pair": key, "expected": expected, "actual": actual, "rows": len(found),
            "basis": prior["basis"], "phase": prior["phase"], "method": prior["method"],
            "n": prior["n"], "vintage": prior["vintage"],
            "passed": len(found) == 1 and abs(actual - expected) <= 1e-15,
        })
    return pd.DataFrame(rows)


def secrets_scan() -> pd.DataFrame:
    roots = [ROOT / "src/five_sector_momentum/v6_3", ROOT / "tests/v6_3", CONFIG, REGISTRY]
    pattern = re.compile(r"(?i)(tushare[_-]?token\s*[:=]|['\"]token['\"]\s*:)")
    rows = []
    paths: list[Path] = []
    for root in roots:
        paths.extend(root.rglob("*") if root.is_dir() else [root])
    for path in paths:
        if path.is_file() and path.suffix.lower() in {".py", ".yaml", ".yml", ".json", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                rows.append({"path": str(path.relative_to(ROOT)), "rule": "TOKEN_ASSIGNMENT_PATTERN"})
    return pd.DataFrame(rows, columns=["path", "rule"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    inventory = whitelist_inventory()
    registry_checks = validate(load(REGISTRY))
    contract_checks, details = data_contract_audit()
    panama, forecasts = panama_prefix_audit()
    correlations = correlation_prior_audit()
    secrets = secrets_scan()
    all_checks = pd.concat([
        inventory[["path", "passed"]].rename(columns={"path": "check"}).assign(group="legacy_hash"),
        registry_checks[["check", "passed"]].assign(group="registry_static"),
        contract_checks[["check", "passed"]].assign(group="data_contract"),
        panama[["check", "passed"]].assign(group="panama"),
        forecasts.assign(check=lambda x: "forecast_prefix_" + x.window.astype(str) + "_skip" + x.skip_recent_days.astype(str))[["check", "passed"]].assign(group="forecast_prefix"),
        correlations.assign(check=lambda x: "correlation_prior_" + x.pair)[["check", "passed"]].assign(group="correlation_prior"),
    ], ignore_index=True)
    hard_contract = contract_checks.loc[contract_checks["severity"].eq("HARD")]
    passed = bool(
        inventory["passed"].all() and registry_checks["passed"].all()
        and hard_contract["passed"].all() and panama["passed"].all()
        and forecasts["passed"].all() and correlations["passed"].all() and secrets.empty
    )

    tables = {
        "expected_artifact_inventory": inventory,
        "registry_static_checks": registry_checks,
        "data_contract_checks": contract_checks,
        "panama_prefix_checks": panama,
        "forecast_prefix_checks": forecasts,
        "correlation_prior_provenance": correlations,
        "secret_scan_findings": secrets,
        "phase0_gate_checks": all_checks,
        **details,
    }
    for name, frame in tables.items():
        write_pair(frame, output / name)
        write_pair(frame, DATA_ROOT / name)

    failed = all_checks.loc[~all_checks["passed"]].copy()
    status = {
        "status": "PHASE0_PASSED_READY_TO_FREEZE" if passed else "BLOCKED_BEFORE_PERFORMANCE",
        "performance_generated": False,
        "attempts_consumed": 0,
        "registry_frozen": False,
        "hard_failed_checks": failed.to_dict("records"),
        "secrets_findings": len(secrets),
        "v6_A01_started": False,
        "v5_started": False,
        "phase0_table_hashes": {name: table_hash(frame) for name, frame in tables.items()},
        "generated_at": pd.Timestamp.now().isoformat(),
    }
    (output / "PHASE0_STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# v6.3 Phase 0 硬化报告", "", f"状态：`{status['status']}`", "",
        "本阶段未生成或查看任何v6.3绩效，完整历史attempt消耗为0。", "",
        "## 闸门摘要", "", f"- 白名单哈希：{int(inventory.passed.sum())}/{len(inventory)}；",
        f"- 注册表静态检查：{int(registry_checks.passed.sum())}/{len(registry_checks)}；",
        f"- 数据契约硬检查：{int(hard_contract.passed.sum())}/{len(hard_contract)}；",
        f"- Panama及forecast前缀：{int(panama.passed.sum()) + int(forecasts.passed.sum())}/{len(panama) + len(forecasts)}；",
        f"- 相关性先验来源：{int(correlations.passed.sum())}/{len(correlations)}；",
        f"- secrets发现：{len(secrets)}。", "",
    ]
    if not passed:
        report += [
            "## 阻断结论", "",
            "至少一个预注册硬闸门失败。按v1.1 FINAL停止：不得冻结绩效注册表，不得运行G01或任何完整历史场景。",
            "", "失败项：", "",
        ]
        report += [f"- `{row.group}` / `{row.check}`" for row in failed.itertuples()]
    (output / "V6_3_PHASE0_HARDENING_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if not passed:
        blocker = [
            "# v6.3 阻断报告", "", "状态：`BLOCKED_BEFORE_PERFORMANCE`", "",
            "Phase 0数据或治理闸门未全部通过。根据研究规范，本轮在任何新增绩效、注册表冻结和完整历史attempt之前停止。",
            "", "## 失败闸门", "",
        ] + [f"- `{row.group}` / `{row.check}`" for row in failed.itertuples()] + [
            "", "## 纪律确认", "",
            "- v6 A01未运行；", "- v6.3 G01/G02及其余场景均未运行；",
            "- v6.3完整历史attempt为0；", "- 未修改任何旧版本数据或结果；",
            "- 未自动修改主力映射或放宽闸门。", "",
            "详细异常见同目录CSV/pickle，尤其 `mapping_backward_expiry_transitions`。",
        ]
        (output / "V6_3_BLOCKER_REPORT.md").write_text("\n".join(blocker) + "\n", encoding="utf-8")
    print(json.dumps({"status": status["status"], "failed": failed.to_dict("records")}, ensure_ascii=False))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
