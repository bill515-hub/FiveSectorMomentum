# -*- coding: utf-8 -*-
"""跨源抽验：用 tushare fut_daily 独立重新拉取随机样本，与仓库 bars 比对（只读仓库；输出到审计tmp）。
token 从仓库 .env 读取（不在任何输出中回显）。
"""
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "audit_20260903_v2" / "tmp"

env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

token = env.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN")
if not token:
    print("NO_TOKEN"); sys.exit(0)

import tushare as ts  # noqa: E402
pro = ts.pro_api(token)

sample = pd.read_csv(OUT / "random_sample_for_crosscheck.csv")
print(f"sample rows: {len(sample)}")

ok, bad, skipped = 0, 0, 0
mismatches = []
for i, row in sample.head(15).iterrows():  # 限流：抽前15个逐一复核
    try:
        df = pro.fut_daily(ts_code=row["ts_code"], start_date=row["date"], end_date=row["date"])
    except Exception as exc:  # tushare SDK 的异常类型不公开
        skipped += 1
        print(f"{row['ts_code']} {row['date']}: FETCH_ERROR {type(exc).__name__}")
        continue
    if df is None or df.empty:
        skipped += 1
        print(f"{row['ts_code']} {row['date']}: EMPTY")
        continue
    r = df.iloc[0]

    def num(value):
        try:
            f = float(value)
            return f if pd.notna(f) else None
        except (TypeError, ValueError):
            return None

    diffs = {}
    for field, repo_col in [("open", "open"), ("high", "high"), ("low", "low"), ("close", "close")]:
        a, b = num(r.get(field)), num(row[repo_col])
        diffs[field] = abs(a - b) if (a is not None and b is not None) else None
    a_s, b_s = num(r.get("settle")), num(row["settlement"])
    diffs["settle"] = abs(a_s - b_s) if (a_s is not None and b_s is not None) else 0.0
    a_v, b_v = num(r.get("vol")), num(row["volume"])
    diffs["vol"] = abs(a_v - b_v) if (a_v is not None and b_v is not None) else 0.0
    numeric = [d for d in diffs.values() if d is not None]
    maxd = max(numeric) if numeric else 0.0
    tag = "MATCH" if (maxd < 1e-6 and len(numeric) >= 4) else "MISMATCH"
    if tag == "MATCH":
        ok += 1
    else:
        bad += 1
        mismatches.append({"ts_code": row["ts_code"], "date": row["date"], **diffs})
    print(f"{row['ts_code']} {row['date']}: {tag} maxdiff={maxd}")

print(f"\nsummary: match={ok}, mismatch={bad}, skipped={skipped}")
if mismatches:
    pd.DataFrame(mismatches).to_csv(OUT / "cross_source_mismatches.csv", index=False)
