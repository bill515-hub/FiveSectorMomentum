# -*- coding: utf-8 -*-
"""T6 价格换源：akshare 新浪 futures_zh_daily_sina vs 仓库 fut_daily（OHLC 逐字段 diff）。rng=20260903。"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import akshare as ak
from pandas import read_pickle  # 仓库自身数据文件（已入 pre_manifest 哈希快照）

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])

rng = np.random.default_rng(20260903)
diff_rows = []
summary_rows = []
for code in ["RB2410.SHF", "T2403.CFX", "SC2409.INE", "AL2406.SHF", "MA409.ZCE"]:
    sym = code.split(".")[0]
    sub = daily[daily.ts_code.eq(code)].dropna(subset=["close"])
    if len(sub) < 20:
        emit(f"{code}: 仓库仅 {len(sub)} 行，跳过"); continue
    take = rng.choice(len(sub), size=20, replace=False)
    sample = sub.iloc[np.sort(take)]
    try:
        sina = ak.futures_zh_daily_sina(symbol=sym)
    except Exception as exc:
        emit(f"{sym}: akshare 获取失败 {type(exc).__name__}: {str(exc)[:120]}"); continue
    if sina is None or sina.empty:
        emit(f"{sym}: akshare 空返回"); continue
    date_col = "date"
    sina[date_col] = pd.to_datetime(sina[date_col])
    smap = sina.set_index(date_col)
    if not summary_rows:
        emit(f"sina columns: {list(sina.columns)}")
    matched = 0; fields_diff = {"open": [], "high": [], "low": [], "close": [], "settle": []}
    colmap = {"open": "open", "high": "high", "low": "low", "close": "close", "settle": "settle"}
    for r in sample.itertuples(index=False):
        if r.trade_date not in smap.index:
            diff_rows.append({"symbol": sym, "date": str(r.trade_date.date()), "field": "ROW",
                              "repo": "has", "sina": "MISSING", "absdiff": np.nan})
            continue
        srow = smap.loc[r.trade_date]
        matched += 1
        for field, scol in colmap.items():
            repo_v = float(getattr(r, field))
            sina_v = float(srow[scol]) if pd.notna(srow[scol]) else np.nan
            d = abs(repo_v - sina_v)
            fields_diff[field].append(d)
            diff_rows.append({"symbol": sym, "date": str(r.trade_date.date()), "field": field,
                              "repo": repo_v, "sina": sina_v, "absdiff": d})
    summary_rows.append({
        "symbol": sym, "repo_rows": len(sub), "sampled": len(sample), "sina_matched": matched,
        **{f"maxdiff_{k}": (max(v) if v else np.nan) for k, v in fields_diff.items()},
    })
    emit(f"{sym}: 采样20 匹配{matched} | maxdiff O/H/L/C = "
         + "/".join(f"{max(v) if v else float('nan'):.4g}" for v in fields_diff.values()))
    time.sleep(1.0)

pd.DataFrame(diff_rows).to_csv(TMP / "price_diff.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(summary_rows).to_csv(TMP / "price_diff_summary.csv", index=False, encoding="utf-8-sig")
emit("\nsummary: " + pd.DataFrame(summary_rows).to_string(index=False))
(REPORTS / "T6_price_cross_source.md").write_text(
    "# T6 价格换源（akshare 新浪 vs 仓库 fut_daily）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT6 DONE")
