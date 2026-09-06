from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pandas as pd


PATTERN = re.compile(r"(?i)(tushare[_-]?token|api[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_-]{16,})")


def scan(paths: list[Path]) -> pd.DataFrame:
    actual = os.getenv("TUSHARE_TOKEN", "")
    findings = []
    for root in paths:
        candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in candidates:
            if path.suffix.lower() in {".pkl", ".pyc", ".png", ".pdf"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if actual and actual in text:
                findings.append({"path": str(path), "rule": "ACTUAL_SECRET", "fingerprint": hashlib.sha256(actual.encode()).hexdigest()[:12]})
            for match in PATTERN.finditer(text):
                value = match.group(2)
                if value.upper() not in {"FORBIDDEN", "ENVIRONMENT"}:
                    findings.append({"path": str(path), "rule": "TOKEN_LIKE_ASSIGNMENT", "fingerprint": hashlib.sha256(value.encode()).hexdigest()[:12]})
    return pd.DataFrame(findings, columns=["path", "rule", "fingerprint"])

