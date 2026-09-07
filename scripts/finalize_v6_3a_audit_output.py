from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/v6_3a_independent_audit_20260907_180842"
EXTERNAL = [
    ROOT / "scripts/v6_3a_independent_audit_v2.py",
    ROOT / "scripts/finalize_v6_3a_audit_output.py",
    ROOT / "tests/v6_3a_postrun/test_independent_audit_metrics.py",
    ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_POSTRUN_AUDIT_ERRATA_v1_1.md",
    ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_SUPPLEMENTAL_FREEZE_ATTESTATION_v1_1.json",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


pattern = re.compile(r"(?i)tushare[_-]?token\s*[:=]\s*['\"]?[0-9a-f]{32,}")
hits = []
for path in [*OUT.rglob("*"), *EXTERNAL]:
    if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".csv", ".yaml"}:
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append({"path": path.relative_to(ROOT).as_posix(), "rule": "TOKEN_ASSIGNMENT"})
scan = pd.DataFrame(hits, columns=["path", "rule"])
scan.to_csv(OUT / "secret_scan_findings.csv", index=False, encoding="utf-8-sig")
scan.to_pickle(OUT / "secret_scan_findings.pkl")
if not scan.empty:
    raise SystemExit("SECRETS_SCAN_FAILED")

manifest = {
    "analysis_only": True,
    "engine_rerun": False,
    "source_run": "outputs/v6_3a_20260907_134158",
    "watermark": "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION",
    "files": [],
    "external_remediation_files": [],
}
for path in sorted(OUT.rglob("*")):
    if path.is_file() and path.name != "manifest.json":
        manifest["files"].append({
            "path": path.relative_to(OUT).as_posix(),
            "sha256": digest(path),
            "bytes": path.stat().st_size,
        })
for path in EXTERNAL:
    manifest["external_remediation_files"].append({
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
    })
(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"secrets": 0, "files": len(manifest["files"]), "external": len(EXTERNAL)}))
