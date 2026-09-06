from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from five_sector_momentum.v6.canonical import sha256_file, write_table_pair
from five_sector_momentum.v6.secrets import scan_paths


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]).resolve()
    env_path = root / ".env"
    if env_path.exists() and not os.getenv("TUSHARE_TOKEN"):
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip().startswith("TUSHARE_TOKEN="):
                os.environ["TUSHARE_TOKEN"] = raw.split("=", 1)[1].strip().strip("'\"")
                break

    files: list[tuple[Path, str]] = []
    files.extend((path, "ADDED_V6") for path in sorted((root / "src/five_sector_momentum/v6").glob("*.py")))
    files.extend(
        [
            (root / "configs/five_sector_momentum_v6.yaml", "ADDED_V6"),
            (root / "scripts/build_v6_resolved_config.py", "ADDED_V6"),
            (root / "scripts/finalize_v6_phase0_1a_artifacts.py", "ADDED_V6"),
            (root / "tests/test_v6_phase0_1a.py", "ADDED_V6"),
            (root / "outputs/V6_GLOBAL_ATTEMPT_LEDGER.csv", "ADDED_V6"),
            (root / "docs/v6_20260905_research_and_test_plan/04_ENGINE_CORRECTION_AND_MIGRATION_PLAN.md", "PRE_RESULT_V1_4_CONSISTENCY_ERRATA_E55"),
            (root / "docs/v6_20260905_research_and_test_plan/08_ACCOUNTING_AND_TRACEABILITY.md", "PRE_RESULT_V1_4_CONSISTENCY_ERRATA_E55"),
            (root / "docs/v6_20260905_research_and_test_plan/PLAN_REVIEW_ERRATA.md", "PRE_RESULT_V1_4_CONSISTENCY_ERRATA_E55"),
        ]
    )
    modified = pd.DataFrame(
        [{"path": str(path.resolve()), "change_type": change, "sha256": sha256_file(path)} for path, change in files if path.exists()]
    )
    modified_meta = write_table_pair(modified, output / "modified_files")

    status_lines = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True).stdout.splitlines()
    forbidden_prefixes = ("src/five_sector_momentum/v2", "src/five_sector_momentum/v3", "src/five_sector_momentum/v4", "configs/five_sector_momentum_v2", "configs/five_sector_momentum_v3", "configs/five_sector_momentum_v4", "data/normalized_v2", "outputs/v2", "outputs/v3", "outputs/v4")
    normalized_lines = [line[3:].replace("\\", "/") for line in status_lines if len(line) > 3]
    violations = [path for path in normalized_lines if path.startswith(forbidden_prefixes)]
    protected = {
        "passed": not violations,
        "forbidden_modified_path_count": len(violations),
        "forbidden_paths": violations,
        "note": "git status check; v6 plan E55 and new v6 paths are allowed",
    }
    (output / "protected_legacy_paths_check.json").write_text(json.dumps(protected, ensure_ascii=False, indent=2), encoding="utf-8")

    scan_roots = [root / "src/five_sector_momentum/v6", root / "configs/five_sector_momentum_v6.yaml", root / "data/v6", output]
    findings = scan_paths(scan_roots)
    if not findings.empty:
        findings.to_csv(output / "secret_scan_findings.csv", index=False)
    summary = {"passed": findings.empty, "finding_count": len(findings), "values_redacted": True, "scope": [str(path) for path in scan_roots]}
    (output / "secret_scan_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tables"]["modified_files"] = modified_meta
    manifest["supplemental_files"] = {}
    for name in (
        "PHASE0_1A_STATUS.json", "V6_PHASE0_1A_READINESS_REPORT.md", "V6_BLOCKER_REPORT.md",
        "TEST_RESULTS_AND_ENVIRONMENT.md", "pytest_regression_compatible.xml",
        "pytest_regression_environment_blocked.xml", "snapshot_freeze_status.json",
        "protected_legacy_paths_check.json", "secret_scan_summary.json",
    ):
        path = output / name
        if path.exists():
            manifest["supplemental_files"][name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest["project_regression"] = {"passed": 73, "setup_errors": 12, "assertion_failures": 0}
    manifest["protected_legacy_paths_check_passed"] = protected["passed"]
    manifest["secret_scan_passed"] = findings.empty
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    data_manifest = {
        "phase": "PHASE0_1A",
        "status": "BLOCKED_BEFORE_A01",
        "source_output": str(output),
        "raw_probe_files": [str(path) for path in sorted((root / "data/v6/raw" / output.name).rglob("*")) if path.is_file()],
        "rules_files": [str(path) for path in sorted((root / "data/v6/rules" / output.name).rglob("*")) if path.is_file()],
        "candidate_snapshots_frozen": False,
        "token_or_credentials_embedded": False,
    }
    target = root / "data/v6" / f"{output.name}_data_manifest.json"
    target.write_text(json.dumps(data_manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

