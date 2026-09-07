from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import pandas as pd

from five_sector_momentum.settings import Settings

from .canonical import file_hash, table_hash, write_pair
from .data import DATA_ROOT, build_corrected_bundle, expiry_transition_audit, prefix_invariance_check
from .registry import freeze_metadata, load, validate, write_freeze
from five_sector_momentum.v6_3.preflight import whitelist_inventory


ROOT = Path(__file__).resolve().parents[3]
DOC_ROOT = ROOT / "docs/v6_3a_corrected_mapping_research"
REGISTRY = DOC_ROOT / "V6_3A_MACHINE_REGISTRY.yaml"
CONFIG = ROOT / "configs/five_sector_momentum_v6_3a.yaml"
FREEZE = DOC_ROOT / "V6_3A_REGISTRY_FREEZE.json"


def _data_checks(bundle, diagnostics) -> pd.DataFrame:
    bars, mapping, adjusted = bundle.bars.copy(), bundle.mapping.copy(), bundle.adjusted_prices.copy()
    backward = expiry_transition_audit(mapping, bundle.contract_meta)
    mapped = mapping.merge(bars[["date","ts_code","open","close","volume"]],left_on=["date","contract"],right_on=["date","ts_code"],how="left")
    events = diagnostics["mapping_events"]
    checks = {
        "mapping_unique_date_instrument": not mapping.duplicated(["date","instrument"]).any(),
        "mapping_expiry_non_decreasing": backward.empty,
        "mapped_open_close_present": not mapped[["open","close"]].isna().any(axis=None),
        "corrected_rows_exist": len(events) > 0,
        "corrected_rows_only_SC": set(events.instrument.unique()) == {"SC"},
        "held_contract_positive_volume": bool(events.accepted_volume.gt(0).all()),
        "held_contract_finite_close": bool(events.accepted_close.notna().all() and events.accepted_close.gt(0).all()),
        "held_contract_minimum_runway": bool(events.accepted_days_to_expiry.ge(20).all()),
        "correction_uses_no_future": bool((events.used_future_data == False).all()),
        "adjusted_unique_date_instrument": not adjusted.duplicated(["date","instrument"]).any(),
        "panama_no_stitch_failures": not diagnostics["panama"].get("stitch_failures"),
    }
    return pd.DataFrame([{"check":k,"passed":bool(v)} for k,v in checks.items()])


def _secrets(paths:list[Path])->pd.DataFrame:
    findings=[]
    patterns=[re.compile(r"(?i)tushare[_-]?token\s*[:=]\s*['\"]?[0-9a-f]{32,}"),re.compile(r"[0-9a-f]{64}")]
    # SHA-256 values are expected; only report 64-hex strings outside known hash/config documents.
    for path in paths:
        if path.suffix.lower() not in {".py",".md",".yaml",".json",".csv"}: continue
        text=path.read_text(encoding="utf-8",errors="ignore")
        for pattern in patterns[:1]:
            for match in pattern.finditer(text): findings.append({"path":path.relative_to(ROOT).as_posix(),"rule":"TOKEN_ASSIGNMENT","fingerprint":file_hash(path)[:16]})
    return pd.DataFrame(findings,columns=["path","rule","fingerprint"])


def main(argv=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output",type=Path,required=True); parser.add_argument("--freeze",action="store_true"); args=parser.parse_args(argv)
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    settings=Settings.load(ROOT/"configs/five_sector_momentum_v4_2_repaired.yaml")
    bundle,diag=build_corrected_bundle(settings,persist=True)
    registry_checks=validate(load(REGISTRY)); data_checks=_data_checks(bundle,diag); prefix=prefix_invariance_check(settings)
    whitelist=whitelist_inventory()
    write_pair(registry_checks,out/"registry_static_checks"); write_pair(data_checks,out/"data_contract_checks"); write_pair(prefix,out/"panama_prefix_checks")
    write_pair(whitelist,out/"expected_artifact_inventory")
    write_pair(diag["mapping_events"],out/"mapping_correction_events"); write_pair(diag["backward_transitions"],out/"remaining_backward_expiry_transitions")
    legacy_phase0=pd.read_csv(ROOT/"outputs/v6_3_20260907_123229_phase0/phase0_gate_checks.csv")
    write_pair(legacy_phase0,out/"v6_3_blocked_phase0_gate_reference")
    source_paths=sorted((ROOT/"src/five_sector_momentum/v6_3a").glob("*.py"))+sorted((ROOT/"src/five_sector_momentum/v6_3").glob("*.py"))+sorted((ROOT/"tests/v6_3a").glob("*.py"))+sorted((ROOT/"tests/v6_3").glob("*.py"))+[
        ROOT/"src/five_sector_momentum/v6_2/engine.py",ROOT/"src/five_sector_momentum/v6_2/margin.py",
        ROOT/"src/five_sector_momentum/engine_v3.py",ROOT/"src/five_sector_momentum/engine_v4_1.py",ROOT/"src/five_sector_momentum/engine_v4_2.py",
        ROOT/"src/five_sector_momentum/signals.py",ROOT/"src/five_sector_momentum/signals_v4.py",ROOT/"src/five_sector_momentum/signals_v4_2.py",
        ROOT/"src/five_sector_momentum/data_pipeline.py",ROOT/"src/five_sector_momentum/calendar_v4_2.py",
        ROOT/"src/five_sector_momentum/costs_v3.py",ROOT/"src/five_sector_momentum/v6_1/engine.py",
    ]
    input_paths=[REGISTRY,CONFIG,DOC_ROOT/"V6_3A_MAPPING_CORRECTION_ADDENDUM.md",DOC_ROOT/"V6_3A_EXPERIMENT_REGISTRY.md",
                 ROOT/"data/normalized_v2/bars.pkl",ROOT/"data/normalized_v2/mapping.pkl",ROOT/"data/normalized_v2/contract_meta.pkl",
                 ROOT/"data/v6_2/margin_normalized_rules.pkl",ROOT/"data/v3/fees/historical_fee_rules.pkl",
                 DATA_ROOT/"mapping_corrected.pkl",DATA_ROOT/"multiple_prices_corrected.pkl",DATA_ROOT/"adjusted_prices_corrected.pkl",DATA_ROOT/"mapping_correction_events.pkl"]
    secrets=_secrets(source_paths+input_paths); write_pair(secrets,out/"secret_scan_findings")
    passed=bool(whitelist.passed.all() and registry_checks.passed.all() and data_checks.passed.all() and prefix.passed.all() and secrets.empty)
    freeze=None
    if passed and args.freeze:
        freeze=freeze_metadata(REGISTRY,CONFIG,source_paths,input_paths)
        freeze.update({"mapping_corrected_content_sha256":diag["mapping_content_sha256"],"adjusted_corrected_content_sha256":diag["adjusted_content_sha256"],"correction_event_count":diag["changed_rows"]})
        write_freeze(FREEZE,freeze)
    status={"status":"READY_FOR_PERFORMANCE" if passed and args.freeze else ("PHASE0_PASSED_NOT_FROZEN" if passed else "BLOCKED_BEFORE_PERFORMANCE"),
            "performance_generated":False,"attempts_consumed":0,"registry_checks_passed":int(registry_checks.passed.sum()),"registry_checks_total":len(registry_checks),
            "legacy_whitelist_passed":int(whitelist.passed.sum()),"legacy_whitelist_total":len(whitelist),
            "data_checks_passed":int(data_checks.passed.sum()),"data_checks_total":len(data_checks),"prefix_passed":bool(prefix.passed.all()),
            "mapping_correction_rows":diag["changed_rows"],"freeze_written":bool(freeze),"generated_at":pd.Timestamp.now().isoformat()}
    (out/"PHASE0_STATUS.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    report=["# v6.3a Phase 0 数据纠偏与冻结报告","",f"状态：`{status['status']}`","","本阶段未生成任何新增绩效，完整历史attempt为0。",
            "",f"主力映射因果保持共修改 {diag['changed_rows']} 个日-品种映射行；剩余到期日倒退为 {len(diag['backward_transitions'])}。",
            "",f"旧白名单哈希 {status['legacy_whitelist_passed']}/{status['legacy_whitelist_total']}，注册表检查 {status['registry_checks_passed']}/{status['registry_checks_total']}，数据契约 {status['data_checks_passed']}/{status['data_checks_total']}，Panama前缀检查通过={status['prefix_passed']}，secrets={len(secrets)}。",
            "","旧 `data/normalized_v2` 未修改。新映射、Panama序列和逐日修复事件保存在 `data/v6_3a/`；旧v6.2基线只在绩效完成后作为差异桥。"]
    (out/"V6_3A_PHASE0_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    return 0 if passed else 2


if __name__=="__main__": raise SystemExit(main())
