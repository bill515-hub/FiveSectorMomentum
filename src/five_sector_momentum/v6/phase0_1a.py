from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts
import yaml

from .adapters import build_expected_artifact_inventory
from .attempt_ledger import attempt_count, exclusive_lock, initialize_ledger
from .canonical import canonical_dataframe_hash, canonical_json_hash, sha256_file, write_table_pair
from .probes import (
    margin_coverage_from_cache,
    probe_ft_limit,
    probe_margin_endpoint,
    probe_next_open,
    select_limit_contracts,
    select_next_open_samples,
)
from .registry import load_registry, resolved_config, validate_registry, validate_resolved_config
from .schemas import ensure_schema
from .secrets import scan_paths
from .events import EventReason
from .units import UNIT_REGISTRY


PLAN_DIR = Path("docs/v6_20260905_research_and_test_plan")
REGISTRY_FILE = PLAN_DIR / "V6_MACHINE_REGISTRY.yaml"
LEDGER_FILE = Path("outputs/V6_GLOBAL_ATTEMPT_LEDGER.csv")
LOCK_FILE = Path("outputs/.v6_global_attempt.lock")


OFFICIAL_LIMIT_SOURCE_CANDIDATES = [
    {
        "exchange": "SHFE", "url": "https://edu.shfe.com.cn/TradingAssistant/RulesIntroduction/518.html",
        "source_type": "OFFICIAL_RULE_PAGE", "coverage_status": "INSUFFICIENT_FOR_DAILY_CAUSAL_RECONSTRUCTION",
        "effective_start": "NOT_ESTABLISHED", "published_at": "NOT_ESTABLISHED", "known_time": "NOT_ESTABLISHED",
        "derivation_formula": "previous_settlement * (1 +/- effective_limit_ratio), then exchange tick rounding",
        "causal_usable": False,
        "note": "general rule framework; does not enumerate every historical effective-date adjustment",
    },
    {
        "exchange": "INE", "url": "https://www.ine.cn/regulation/ineregulation/rules/202606/t20260622_832199.html",
        "source_type": "OFFICIAL_RULE_PAGE", "coverage_status": "INSUFFICIENT_FOR_DAILY_CAUSAL_RECONSTRUCTION",
        "effective_start": "2026-06-22_CURRENT_PAGE_ONLY", "published_at": "2026-06-22", "known_time": "PAGE_PUBLICATION_TIME_NOT_CAPTURED",
        "derivation_formula": "previous_settlement * (1 +/- effective_limit_ratio), then exchange tick rounding",
        "causal_usable": False,
        "note": "current risk rules; does not alone establish all 2015-2026 contract-day limits",
    },
    {
        "exchange": "CZCE", "url": "https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/zcjjygz/2026/3/68c0dce01f984475be768ed93afd9b4f.pdf",
        "source_type": "OFFICIAL_RULE_PDF", "coverage_status": "INSUFFICIENT_FOR_DAILY_CAUSAL_RECONSTRUCTION",
        "effective_start": "2026_CURRENT_RULEBOOK_ONLY", "published_at": "2026-03_DATE_FROM_URL_ONLY", "known_time": "NOT_ESTABLISHED",
        "derivation_formula": "previous_settlement * (1 +/- effective_limit_ratio), then exchange tick rounding",
        "causal_usable": False,
        "note": "rulebook candidate; temporary notices and historical versions remain required",
    },
    {
        "exchange": "DCE", "url": "https://www.dce.com.cn/dalianshangpin/resource/cms/2016/11/%E7%8E%89%E7%B1%B3%E6%B7%80%E7%B2%89%E6%9C%9F%E8%B4%A7%E5%90%88%E7%BA%A6%E8%AE%BE%E8%AE%A1%E8%AF%B4%E6%98%8E.pdf", "source_type": "OFFICIAL_PRODUCT_RULE_PDF",
        "coverage_status": "INSUFFICIENT_FOR_DAILY_CAUSAL_RECONSTRUCTION", "effective_start": "HISTORICAL_PRODUCT_DOCUMENT_ONLY", "published_at": "2016-11_DATE_FROM_URL_ONLY", "known_time": "NOT_ESTABLISHED", "derivation_formula": "previous_settlement * (1 +/- effective_limit_ratio), then exchange tick rounding", "causal_usable": False, "note": "official product material confirms the framework but is not a five-exchange effective-dated rule corpus",
    },
    {
        "exchange": "CFFEX", "url": "https://www.cffex.com.cn/cn/ssxz/20230414/43079.html", "source_type": "OFFICIAL_RULE_PAGE",
        "coverage_status": "INSUFFICIENT_FOR_DAILY_CAUSAL_RECONSTRUCTION", "effective_start": "2023-04-14_CURRENT_VERSION", "published_at": "2023-04-14", "known_time": "PAGE_PUBLICATION_TIME_NOT_CAPTURED", "derivation_formula": "previous_settlement * (1 +/- effective_limit_ratio), then exchange tick rounding", "causal_usable": False, "note": "version history and general risk rules exist, but product parameters and temporary notices remain required",
    },
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _plan_hashes(project_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted((project_root / PLAN_DIR).glob("*")):
        if path.is_file():
            rows.append({"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return ensure_schema("plan_hashes", rows)


def _static_checks(registry: dict[str, Any], inventory: pd.DataFrame, config: dict[str, Any], plan_hashes: pd.DataFrame) -> pd.DataFrame:
    facts = validate_registry(registry)
    validate_resolved_config(config, registry)
    checks = [
        ("REGISTRY_VERSION", "1.4", facts.version, facts.version == "1.4", "machine authority"),
        ("SCENARIO_COUNT", 44, facts.scenarios, facts.scenarios == 44, "sequence 1..44 and unique IDs checked"),
        ("BASE_STRATEGY_COUNT", 22, facts.strategies, facts.strategies == 22, "provider scenarios resolve"),
        ("SINGLE_FACTOR_EDGE_COUNT", 12, facts.comparisons, facts.comparisons == 12, "registered comparison graph"),
        ("GLOBAL_ATTEMPT_CAP", 48, facts.attempt_cap, facts.attempt_cap == 48, "probe runs are excluded"),
        ("CORE_ARTIFACTS", 0, int((inventory.status == "BLOCKER_MISSING_CORE").sum()), not (inventory.status == "BLOCKER_MISSING_CORE").any(), "whitelist inventory"),
        ("PLAN_HASH_COUNT", ">=17", len(plan_hashes), len(plan_hashes) >= 17, "all plan files included after pre-result E55 correction"),
        ("FULL_HISTORY_LAUNCHER", False, config["v6_runtime"]["full_history_launcher_enabled"], config["v6_runtime"]["full_history_launcher_enabled"] is False, "Phase 0/1A scope only"),
        ("BROKER_FORCED_LIQUIDATION", False, registry["common_parameters"]["margin"]["broker_forced_liquidation_model_enabled"], registry["common_parameters"]["margin"]["broker_forced_liquidation_model_enabled"] is False, "65%/78% are target constraints"),
    ]
    return ensure_schema("registry_static_validation", [dict(zip(["check_id", "expected", "actual", "passed", "detail"], row)) for row in checks])


def _build_tushare_client(project_root: Path):
    env_path = project_root / ".env"
    if env_path.exists() and not os.getenv("TUSHARE_TOKEN"):
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "TUSHARE_TOKEN":
                os.environ["TUSHARE_TOKEN"] = value.strip().strip("'\"")
                break
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is unavailable in the project secure environment")
    return ts.pro_api(token)


def _evaluate(
    static: pd.DataFrame,
    inventory: pd.DataFrame,
    limits: pd.DataFrame,
    margin: pd.DataFrame,
    next_open: pd.DataFrame,
    secret_findings: pd.DataFrame,
    tests_passed: bool,
) -> tuple[str, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    if not static.passed.astype(bool).all():
        failures.append({"gate": "G0", "reason": "STATIC_VALIDATION_FAILED", "detail": static.loc[~static.passed.astype(bool), "check_id"].tolist()})
    if (inventory.status == "BLOCKER_MISSING_CORE").any():
        failures.append({"gate": "G0", "reason": "MISSING_CORE_COMPATIBILITY_ARTIFACT", "detail": inventory.loc[inventory.status == "BLOCKER_MISSING_CORE", "path"].tolist()})
    if len(limits) != 10 or not (limits.classification == "DATA").all():
        failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "FT_LIMIT_NOT_AVAILABLE_FOR_ALL_10_PROBES", "detail": limits.classification.value_counts().to_dict()})
    # Endpoint availability is not the same as formal A01/A04 order-key coverage.
    failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "FORMAL_LIMIT_COVERAGE_NOT_PROVEN_100_PERCENT", "detail": "No complete pre-market effective-dated daily rule table was frozen for all A01/A04 order keys."})
    overall_margin = margin[margin.instrument == "ALL"]
    if overall_margin.empty or not overall_margin.passed.astype(bool).all():
        failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "OFFICIAL_OR_DERIVED_MARGIN_COVERAGE_BELOW_95_PERCENT", "detail": overall_margin[["scope", "official_or_derived_rate"]].to_dict("records")})
    inst_margin = margin[margin.instrument != "ALL"]
    if inst_margin.empty or not inst_margin.passed.astype(bool).all():
        failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "INSTRUMENT_YEAR_MARGIN_COVERAGE_BELOW_80_PERCENT", "detail": int((~inst_margin.passed.astype(bool)).sum())})
    if len(next_open) != 75:
        failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "NEXT_OPEN_SAMPLE_COUNT_NOT_75", "detail": len(next_open)})
    else:
        rates = next_open.groupby("instrument").matched.mean().to_dict()
        if set(rates) != {"RB", "SC", "M", "TA", "T"} or any(rate < 1.0 for rate in rates.values()):
            failures.append({"gate": "G0_DATA_FEASIBILITY", "reason": "NEXT_OPEN_SESSION_MATCH_BELOW_100_PERCENT", "detail": rates})
    if not secret_findings.empty:
        failures.append({"gate": "G0", "reason": "SECRET_SCAN_FINDINGS", "detail": len(secret_findings)})
    if not tests_passed:
        failures.append({"gate": "G0", "reason": "AUTOMATED_TESTS_FAILED", "detail": "see test logs"})
    return ("BLOCKED_BEFORE_A01" if failures else "READY_FOR_A01"), failures


def _report_text(status: str, output_dir: Path, facts: Any, failures: list[dict[str, Any]], tables: dict[str, dict[str, str]], test_summary: dict[str, Any]) -> str:
    blockers = "\n".join(f"- {item['gate']} / {item['reason']}：{item['detail']}" for item in failures) or "- 无。"
    return f"""# v6 Phase 0 / Phase 1A 就绪性报告

## 1. 结论

状态：**{status}**。本轮只执行了 Phase 0 与 Phase 1A；未启动 A01，未运行任何完整历史回测，未消耗完整历史 attempt。

机器权威经校验为 registry v{facts.version}：44 个场景、22 个基础策略、12 条单因素比较边、全局 48 次 attempt 上限。计划语义哈希为 `{facts.semantic_hash}`。

## 2. 阻断项

{blockers}

只要上述任一硬阈值不满足，v1.4 规定必须停在 A01 之前；不能自动改成 PROVISIONAL，也不能用 `high==low` 反推开盘前限价。

## 3. 历史证据清单

对白名单 v3/v4.2 输出仅做只读盘点。核心 orders、fills、positions、daily_equity 缺失会阻断；历史从未产生的辅助表标记为 NOT_APPLICABLE。详见 `expected_artifact_inventory.csv`。

## 4. 三项数据探针

- `ft_limit`：五所各一个历史合约和一个截至回测终点的活跃合约，共 10 个；错误只保存分类与不可逆指纹，不保存凭据或原始错误全文。
- 保证金：对 2015—2020 SHFE/INE 暴露合约逐合约调用 `fut_settle`，同时统计本地缓存的供应商逐日覆盖。供应商字段在未经交易所原始规则核验前不会被冒充为“官方”。
- `next_open`：RB、SC、M、TA、T 各固定种子抽取 15 点，共 75 点；要求每品种 100% 与分钟首个交易时段开盘相符。

若 `ft_limit` 不可用，本轮只建立了官方规则来源候选及缺口表；现有材料不足以为五所 2015—2026 每个合约日重建可证明的因果限价，因此没有伪造规则或宣称 100% 覆盖。OHLC 的 high/low 没有参与规则推导。

## 5. 保证金和破产语义

65% 商品与 78% 总保证金利用率只约束目标仓位。日终实际超限只记录诊断并在下一次标准目标计算降险。本包不存在 `MARGIN_CALL_LIQUIDATION` 或强平状态机。权益小于等于零只允许写入 `ACCOUNT_INSOLVENT`、保留部分账本并停止，禁止合成有限责任收益曲线。

## 6. G0 测试

测试命令：`{test_summary.get('command', '')}`；退出码 `{test_summary.get('exit_code')}`；通过 `{test_summary.get('passed')}`。迷你市场覆盖跨零拆单、开/平今/平昨费用、整数 tick、涨跌停方向、参与率部分成交、换月双腿、袖套净额、最终约束只作用一次、保证金超限诊断和破产即停。

## 7. 哈希、秘密和追溯

计划、配置、所有 CSV/pickle 内容与原始文件哈希均已输出。规范内容哈希使用 `canonical_json_rows_v1`，不把 pickle 字节当业务身份。新 v6 路径和本轮输出执行了 secrets 扫描；报告与 manifest 不包含 Tushare token。

## 8. 输出索引

输出目录：`{output_dir}`。

""" + "\n".join(f"- `{name}`：CSV `{meta.get('csv','')}`；pickle `{meta.get('pickle','')}`；内容哈希 `{meta.get('content_sha256','')}`" for name, meta in tables.items()) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-online", action="store_true")
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    lock_path = project_root / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(lock_descriptor, str(os.getpid()).encode("ascii"))

    def _release_lock() -> None:
        try:
            os.close(lock_descriptor)
        except OSError:
            pass
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    atexit.register(_release_lock)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (args.output_dir or project_root / f"outputs/v6_{timestamp}_phase0_1a").resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = project_root / "data/v6/raw" / output_dir.name
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = project_root / "data/v6/normalized" / output_dir.name
    normalized_dir.mkdir(parents=True, exist_ok=True)
    rules_dir = project_root / "data/v6/rules" / output_dir.name
    rules_dir.mkdir(parents=True, exist_ok=True)

    registry_path = project_root / REGISTRY_FILE
    registry = load_registry(registry_path)
    facts = validate_registry(registry)
    config = resolved_config(registry, registry_path)
    config_path = project_root / "configs/five_sector_momentum_v6.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    validate_resolved_config(yaml.safe_load(config_path.read_text(encoding="utf-8")), registry)

    initialize_ledger(project_root / LEDGER_FILE)
    before_attempts = attempt_count(project_root / LEDGER_FILE)
    tables: dict[str, dict[str, str]] = {}
    plan_hashes = _plan_hashes(project_root)
    inventory = build_expected_artifact_inventory(project_root)
    static = _static_checks(registry, inventory, config, plan_hashes)
    tables["plan_hashes"] = write_table_pair(plan_hashes, output_dir / "plan_hashes")
    tables["expected_artifact_inventory"] = write_table_pair(inventory, output_dir / "expected_artifact_inventory")
    tables["registry_static_validation"] = write_table_pair(static, output_dir / "registry_static_validation")
    unit_table = pd.DataFrame([{"field": key, "unit": value} for key, value in UNIT_REGISTRY.items()])
    tables["unit_registry"] = write_table_pair(unit_table, output_dir / "unit_registry")
    reason_table = pd.DataFrame([{"reason_code": reason.value, "forced_liquidation": False} for reason in EventReason])
    tables["event_reason_registry"] = write_table_pair(reason_table, output_dir / "event_reason_registry")

    source_table = pd.DataFrame(OFFICIAL_LIMIT_SOURCE_CANDIDATES)
    tables["official_limit_rule_source_candidates"] = write_table_pair(source_table, rules_dir / "official_limit_rule_source_candidates")

    errors = []
    if args.skip_online:
        contracts = select_limit_contracts(pd.read_pickle(project_root / "data/raw/tushare/fut_basic.pkl"))
        limits = ensure_schema("limit_endpoint_probe", [{"exchange": r.exchange, "contract_role": r.contract_role, "ts_code": r.ts_code, "instrument": r.instrument, "query_start": None, "query_end": None, "classification": "SKIPPED", "row_count": 0, "error_class": "", "error_fingerprint": "", "content_hash": None} for r in contracts.itertuples()])
        margin_endpoint = ensure_schema("margin_endpoint_probe", [])
        fresh_margin = pd.DataFrame()
        samples = select_next_open_samples(project_root)
        next_open = ensure_schema("next_open_validation", [{"instrument": r.instrument, "ts_code": r.ts_code, "trade_date": pd.Timestamp(r.date).date().isoformat(), "daily_open": r.open_price, "minute_first_time": None, "minute_first_open": None, "session": None, "classification": "SKIPPED", "matched": False, "error_class": "", "error_fingerprint": ""} for r in samples.itertuples()])
    else:
        pro = _build_tushare_client(project_root)
        contracts = select_limit_contracts(pd.read_pickle(project_root / "data/raw/tushare/fut_basic.pkl"))
        limits, err = probe_ft_limit(pro, contracts, raw_dir / "ft_limit")
        errors.append(err)
        margin_endpoint, fresh_margin, err = probe_margin_endpoint(pro, project_root, raw_dir / "fut_settle")
        errors.append(err)
        samples = select_next_open_samples(project_root)
        next_open, err = probe_next_open(pro, samples, raw_dir / "ft_mins")
        errors.append(err)
    margin = margin_coverage_from_cache(project_root, fresh_margin)
    probe_errors = pd.concat(errors, ignore_index=True) if errors else ensure_schema("probe_errors", [])
    tables["limit_endpoint_probe"] = write_table_pair(limits, output_dir / "limit_endpoint_probe")
    tables["margin_endpoint_probe"] = write_table_pair(margin_endpoint, output_dir / "margin_endpoint_probe")
    tables["margin_coverage_probe"] = write_table_pair(margin, output_dir / "margin_coverage_probe")
    tables["next_open_validation"] = write_table_pair(next_open, output_dir / "next_open_validation")
    tables["probe_errors"] = write_table_pair(probe_errors, output_dir / "probe_errors")
    tables["limit_probe_contracts"] = write_table_pair(contracts, output_dir / "limit_probe_contracts")
    tables["next_open_samples"] = write_table_pair(samples, output_dir / "next_open_samples")

    test_log = output_dir / "pytest_v6_phase0_1a.log"
    test_python = os.getenv("V6_TEST_PYTHON", sys.executable)
    command = [test_python, "-m", "pytest", "-q", "tests/test_v6_phase0_1a.py"]
    test_env = os.environ.copy()
    test_env["PYTHONPATH"] = str(project_root / "src") + os.pathsep + test_env.get("PYTHONPATH", "")
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, env=test_env)
    test_log.write_text((completed.stdout or "") + (completed.stderr or ""), encoding="utf-8")
    test_summary = {"command": " ".join(command), "exit_code": completed.returncode, "passed": completed.returncode == 0, "log_sha256": sha256_file(test_log)}

    secret_findings = scan_paths([project_root / "src/five_sector_momentum/v6", config_path, output_dir, raw_dir, normalized_dir, rules_dir])
    if not secret_findings.empty:
        secret_findings.to_csv(output_dir / "secret_scan_findings.csv", index=False)
    _write_json(output_dir / "secret_scan_summary.json", {"passed": secret_findings.empty, "finding_count": len(secret_findings), "values_redacted": True})

    after_attempts = attempt_count(project_root / LEDGER_FILE)
    if after_attempts != before_attempts:
        static.loc[len(static)] = ["FULL_HISTORY_ATTEMPT_DELTA", 0, after_attempts - before_attempts, False, "probes must not consume full-history attempts"]
        tables["registry_static_validation"] = write_table_pair(static, output_dir / "registry_static_validation")
    status, failures = _evaluate(static, inventory, limits, margin, next_open, secret_findings, completed.returncode == 0)
    status_payload = {
        "status": status,
        "registry_version": facts.version,
        "registry_semantic_sha256": facts.semantic_hash,
        "registry_file_sha256": sha256_file(registry_path),
        "plan_bundle_content_sha256": canonical_dataframe_hash(plan_hashes, sort_by=["path"]),
        "output_dir": str(output_dir),
        "full_history_launcher_invoked": False,
        "full_history_attempt_count_before": before_attempts,
        "full_history_attempt_count_after": after_attempts,
        "A01_started": False,
        "provisional_fallback_used": False,
        "snapshots_frozen": status == "READY_FOR_A01",
        "failures": failures,
        "generated_at": datetime.now().isoformat(),
    }
    _write_json(output_dir / "PHASE0_1A_STATUS.json", status_payload)
    snapshot_status = {
        "status": status,
        "legacy_compat_snapshot": "FROZEN_CANDIDATE" if status == "READY_FOR_A01" else "NOT_FROZEN_BLOCKED",
        "corrected_v6_snapshot": "FROZEN_CANDIDATE" if status == "READY_FOR_A01" else "NOT_FROZEN_BLOCKED",
        "difference_whitelist": "FROZEN" if status == "READY_FOR_A01" else "NOT_FROZEN_BLOCKED",
        "reason": "Phase 1A hard gates must all pass before candidate snapshots can be frozen",
    }
    _write_json(output_dir / "snapshot_freeze_status.json", snapshot_status)
    _write_json(normalized_dir / "snapshot_freeze_status.json", snapshot_status)
    report = _report_text(status, output_dir, facts, failures, tables, test_summary)
    (output_dir / "V6_PHASE0_1A_READINESS_REPORT.md").write_text(report, encoding="utf-8")
    if status == "BLOCKED_BEFORE_A01":
        blocker = "# v6 A01 前阻断报告\n\n状态：**BLOCKED_BEFORE_A01**。未运行 A01 或任何完整历史回测，未自动降级 PROVISIONAL。\n\n" + "\n".join(f"- `{x['gate']}` / `{x['reason']}`：{x['detail']}" for x in failures) + "\n\n解除阻断后必须重新执行 Phase 1A 全部闸门，不得跳过。\n"
        (output_dir / "V6_BLOCKER_REPORT.md").write_text(blocker, encoding="utf-8")

    modified = []
    for path in sorted((project_root / "src/five_sector_momentum/v6").glob("*.py")):
        modified.append({"path": str(path.resolve()), "change_type": "ADDED_V6", "sha256": sha256_file(path)})
    for path in (config_path, project_root / LEDGER_FILE):
        modified.append({"path": str(path.resolve()), "change_type": "ADDED_V6", "sha256": sha256_file(path)})
    for path in (
        project_root / PLAN_DIR / "04_ENGINE_CORRECTION_AND_MIGRATION_PLAN.md",
        project_root / PLAN_DIR / "08_ACCOUNTING_AND_TRACEABILITY.md",
        project_root / PLAN_DIR / "PLAN_REVIEW_ERRATA.md",
    ):
        modified.append({"path": str(path.resolve()), "change_type": "PRE_RESULT_V1_4_CONSISTENCY_ERRATA_E55", "sha256": sha256_file(path)})
    modified_frame = ensure_schema("modified_files", modified)
    tables["modified_files"] = write_table_pair(modified_frame, output_dir / "modified_files")
    manifest = {"status": status, "tables": tables, "test_summary": test_summary, "status_file": "PHASE0_1A_STATUS.json", "report": "V6_PHASE0_1A_READINESS_REPORT.md", "blocker_report": "V6_BLOCKER_REPORT.md" if status == "BLOCKED_BEFORE_A01" else None}
    _write_json(output_dir / "manifest.json", manifest)
    # Final scan includes manifest/report; values remain redacted.
    final_findings = scan_paths([output_dir, config_path])
    _write_json(output_dir / "secret_scan_summary.json", {"passed": final_findings.empty, "finding_count": len(final_findings), "values_redacted": True})
    print(json.dumps({"status": status, "output_dir": str(output_dir), "tests_passed": completed.returncode == 0, "full_history_attempt_delta": after_attempts - before_attempts}, ensure_ascii=False))
    return 0 if completed.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
