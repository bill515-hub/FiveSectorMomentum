# -*- coding: utf-8 -*-
"""T2a 端点诊断：tushare fut_settle / ft_limit 单合约 vs 批量（token 从 ROOT/.env 读，绝不回显）。"""
import os
import time
from pathlib import Path

import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"

env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
token = env.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN")
if not token:
    print("NO_TOKEN"); raise SystemExit(0)

import tushare as ts
pro = ts.pro_api(token)

BATCH = "RB2410.SHF,MA401.ZCE,T2403.CFX,AL2406.SHF,SC2409.INE,FG405.ZCE"

def call(name, **kwargs):
    try:
        df = getattr(pro, name)(**kwargs)
        if df is None:
            return "None", 0, []
        return "ok", len(df), list(df.columns)[:12]
    except Exception as exc:  # tushare SDK 异常类型不公开
        return f"ERROR:{type(exc).__name__}: {str(exc)[:180]}", -1, []

cases = [
    # (端点, 说明, kwargs)
    ("fut_settle", "单合约 RB2410.SHF", dict(ts_code="RB2410.SHF", start_date="20240501", end_date="20240930")),
    ("fut_settle", "单合约 MA401.ZCE", dict(ts_code="MA401.ZCE", start_date="20230901", end_date="20231231")),
    ("fut_settle", "单合约 T2403.CFX", dict(ts_code="T2403.CFX", start_date="20231001", end_date="20240315")),
    ("fut_settle", "批量6合约(data_source同形)", dict(ts_code=BATCH, start_date="20230901", end_date="20240930")),
    ("ft_limit", "单合约 RB2410.SHF", dict(ts_code="RB2410.SHF", start_date="20240501", end_date="20240930")),
    ("ft_limit", "单合约 MA401.ZCE", dict(ts_code="MA401.ZCE", start_date="20230901", end_date="20231231")),
    ("ft_limit", "批量6合约(data_source同形)", dict(ts_code=BATCH, start_date="20230901", end_date="20240930")),
]
rows = []
for endpoint, desc, kwargs in cases:
    status, n, cols = call(endpoint, **kwargs)
    rows.append({"endpoint": endpoint, "case": desc, "status": status, "rows": n, "columns": cols})
    print(f"{endpoint:10s} | {desc:28s} | {status[:60]:60s} | rows={n}", flush=True)
    time.sleep(0.6)

pd.DataFrame(rows).to_csv(TMP / "t2a_endpoint_diagnostics.csv", index=False, encoding="utf-8-sig")
print("saved t2a_endpoint_diagnostics.csv")
