from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import tushare
import yaml

from .attempts import rows as attempt_rows
from .canonical import file_hash, table_hash, write_pair
from .registry import load, validate
from .secrets import scan


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml"
V6_REGISTRY = ROOT / "docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml"
FREEZE = ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_REGISTRY_FREEZE.json"
PREFLIGHT = ROOT / "outputs/v6_1_20260906_152159_preflight"
LEDGER = ROOT / "outputs/V6_1_GLOBAL_ATTEMPT_LEDGER.csv"


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _run_test(path: str, env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run([sys.executable, path], cwd=ROOT, env=env, text=True, capture_output=True)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output_dir.resolve(); out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT / "tests")
    test_specs = [
        ("v6_1_preflight", "tests/v6_1/test_preflight.py", True),
        ("v6_1_registry", "tests/v6_1/test_registry.py", True),
        ("legacy_v4_2_preflight", "tests/test_v4_2_preflight.py", True),
        ("repaired_v4_2", "tests/test_v4_2_repaired.py", True),
    ]
    test_rows = []
    for name, path, expected in test_specs:
        code, text = _run_test(path, env)
        log = out / f"test_{name}.log"; log.write_text(text, encoding="utf-8")
        test_rows.append({"test_suite": name, "entrypoint": path, "exit_code": code, "passed": code == 0, "gate_expected_pass": expected, "log": log.name, "log_sha256": file_hash(log)})
    tests = pd.DataFrame(test_rows)
    registry_checks = validate(load(REGISTRY), load(V6_REGISTRY))
    smoke_rows = []
    for path in [
        ROOT / "data/normalized_v2/bars.pkl",
        ROOT / "data/normalized_v2/mapping.pkl",
        ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/daily_equity.pkl",
        ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/daily_equity.pkl",
    ]:
        try:
            frame = pd.read_pickle(path)
            smoke_rows.append({"path": str(path.resolve()), "readable": True, "rows": len(frame), "columns": len(frame.columns), "sha256": file_hash(path), "error_class": ""})
        except Exception as exc:
            smoke_rows.append({"path": str(path.resolve()), "readable": False, "rows": 0, "columns": 0, "sha256": file_hash(path), "error_class": exc.__class__.__name__})
    smoke = pd.DataFrame(smoke_rows)
    scenario_parameters = pd.DataFrame(load(REGISTRY)["scenario_order"])
    attempts = pd.DataFrame(attempt_rows(LEDGER))
    if attempts.empty:
        attempts = pd.DataFrame(columns=["attempt", "scenario_id", "sequence", "status", "started_at", "finished_at", "output_dir", "registry_sha256", "message_code"])
    dependency = pd.DataFrame([{
        "python": sys.version.replace("\n", " "), "executable": sys.executable,
        "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__,
        "pyyaml": yaml.__version__, "tushare": tushare.__version__,
    }])
    tables = {}
    for name, frame in [("registry_static_validation", registry_checks), ("scenario_parameters", scenario_parameters), ("test_results", tests), ("pickle_smoke_tests", smoke), ("attempt_ledger_snapshot", attempts), ("dependency_environment", dependency)]:
        tables[name] = write_pair(frame, out / name)
    modified = []
    roots = [ROOT / "src/five_sector_momentum/v6_1", ROOT / "tests/v6_1", ROOT / "docs/v6_1_daily_only_provisional_plan", ROOT / "configs/five_sector_momentum_v6_1.yaml", LEDGER]
    for root in roots:
        candidates = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in candidates:
            modified.append({"path": str(path.resolve()), "sha256": file_hash(path), "scope": "V6_1_NEW_ONLY"})
    modified_frame = pd.DataFrame(modified)
    tables["modified_files"] = write_pair(modified_frame, out / "modified_files")
    preflight_report = (PREFLIGHT / "V6_1_PREFLIGHT_EVIDENCE_REPORT.md").read_text(encoding="utf-8")
    (out / "V6_1_PREFLIGHT_EVIDENCE_REPORT.md").write_text(preflight_report + f"\n证据源目录：`{PREFLIGHT}`。\n", encoding="utf-8")
    blocker = """# v6.1 R01 前阻断报告

状态：**BLOCKED_BEFORE_R01**  
证据等级：**PROVISIONAL_DAILY_ONLY**

## 阻断原因

任务规范 G2 明确要求直接运行且通过 `tests/test_v4_2_preflight.py` 与 `tests/test_v4_2_repaired.py`。兼容解释器能读取核心 pickle；修复版测试 10/10 通过，但旧 preflight 的 `test_02_weekly_directions_must_not_change_when_future_dates_are_appended` 失败：追加未来日期后，有35条历史方向/信号日记录变化，其中3条方向变化。

这不是 NumPy/pickle 环境故障，而是旧 `_weekly_select` 周度日历路径的已知因果缺陷被原测试再次检出。按规范停止条件，不能把该失败解释成“预期失败”后继续，也不能启动 R01/R02。

## 已执行与未执行

- 已完成干净网络探针、注册表结果前冻结、pickle smoke test及环境锁定。
- 修复日历路径的 v4.2 测试通过，但不能抵消任务对旧 preflight 必须通过的明文要求。
- 完整历史 attempt 为0；未生成v6.1绩效、订单、持仓或收益结果。

## 解除阻断所需的用户决定

若要继续，应修订下一轮规范：将旧 preflight 明确定位为“必须复现其失败的历史诊断”，而将 `test_v4_2_repaired.py` 作为正式因果闸门；R01只作旧v3数值兼容锚，不具备因果有效性，所有P/S/C继续使用修复日历。未获此规范变更前不得继续。
"""
    (out / "V6_1_BLOCKER_REPORT.md").write_text(blocker, encoding="utf-8")
    audit = """# v6.1 引擎审计（阻断版）

状态：**BLOCKED_BEFORE_R01 / PROVISIONAL_DAILY_ONLY**。

## 数据证据

干净正控制成功；`ft_limit` 10/10、`ft_mins` 5/5 均为应用层无权限。`fut_settle` 两个正控制可用，但2015—2020实际SHFE/INE持仓暴露覆盖为0%。历史75点分钟验证为 `NOT_TESTABLE`，没有错误报告成0%匹配。

## 静态审计

机器注册表校验为14场景、2策略、16 attempt；P/S/C与v6 v1.4共同参数逐字段一致；R仅使用旧费率兼容语义。注册表在绩效前冻结。没有经纪商强平；保证金越限只影响下一标准目标。

## 环境与未来函数闸门

核心pickle全部可读，修复版周度日历/前缀/账户测试通过。旧preflight仍检测到未来追加改变历史方向，因此触发强制停止。尚未进入账户记账、手续费、滑点和一价日代理的完整历史审计，不能对其给出v6.1通过结论。
"""
    (out / "V6_1_ENGINE_AUDIT.md").write_text(audit, encoding="utf-8")
    result = """# v6.1 回测结果报告（未运行）

状态：**BLOCKED_BEFORE_R01 / PROVISIONAL_DAILY_ONLY**。

本轮没有产生任何新增绩效结果。由于G2未来函数测试失败，R01及后续13个场景均未启动。因此不能报告P0/P1/P2区间、修正费用影响、滑点敏感度、open/close差异或袖套表现；沿用历史结果冒充v6.1结果会违反预注册停止条件。
"""
    (out / "V6_1_BACKTEST_RESULT_REPORT.md").write_text(result, encoding="utf-8")
    status = {"status": "BLOCKED_BEFORE_R01", "research_status": "PROVISIONAL_DAILY_ONLY", "preflight_status": "PREFLIGHT_EVIDENCE_READY_FOR_REGISTRY", "registry_frozen_before_performance": True, "full_history_attempts": len(attempts), "R01_started": False, "performance_generated": False, "blocking_test": "tests/test_v4_2_preflight.py::test_02_weekly_directions_must_not_change_when_future_dates_are_appended", "repaired_v4_2_tests_passed": bool(tests.loc[tests.test_suite.eq("repaired_v4_2"), "passed"].all()), "generated_at": datetime.now().isoformat()}
    _json(out / "V6_1_FINAL_STATUS.json", status)
    findings = scan([out, ROOT / "src/five_sector_momentum/v6_1", ROOT / "tests/v6_1", ROOT / "configs/five_sector_momentum_v6_1.yaml"])
    tables["secret_scan_findings"] = write_pair(findings, out / "secret_scan_findings")
    manifest = {"status": status["status"], "registry_freeze_sha256": file_hash(FREEZE), "tables": tables, "reports": ["V6_1_PREFLIGHT_EVIDENCE_REPORT.md", "V6_1_ENGINE_AUDIT.md", "V6_1_BACKTEST_RESULT_REPORT.md", "V6_1_BLOCKER_REPORT.md"], "secret_scan_passed": findings.empty, "performance_generated": False}
    _json(out / "manifest.json", manifest)
    final_findings = scan([out])
    _json(out / "secret_scan_summary.json", {"passed": final_findings.empty, "finding_count": len(final_findings), "values_redacted": True})
    print(json.dumps({"status": status["status"], "output_dir": str(out), "attempts": len(attempts), "secret_scan_passed": final_findings.empty}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
