from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pandas as pd


TOKEN_ASSIGNMENT = re.compile(r"(?i)(tushare[_-]?token|api[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_-]{16,})")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def scan_paths(paths: list[Path]) -> pd.DataFrame:
    actual = os.getenv("TUSHARE_TOKEN", "")
    records: list[dict] = []
    for root in paths:
        candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in candidates:
            if path.suffix.lower() in {".pkl", ".png", ".jpg", ".pdf", ".pyc"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if actual and actual in text:
                records.append({"path": str(path), "rule": "ACTUAL_TOKEN_VALUE", "fingerprint": _fingerprint(actual)})
            for match in TOKEN_ASSIGNMENT.finditer(text):
                value = match.group(2)
                if value.upper() not in {"ENVIRONMENT", "FORBIDDEN", "PROJECT_EXISTING_SECURE_ENVIRONMENT"}:
                    records.append({"path": str(path), "rule": "TOKEN_LIKE_ASSIGNMENT", "fingerprint": _fingerprint(value)})
    return pd.DataFrame(records, columns=["path", "rule", "fingerprint"])

