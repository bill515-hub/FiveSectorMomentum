# -*- coding: utf-8 -*-
"""T7b 新浪主力连续交叉（中文列名适配）。"""
import time
from pathlib import Path

import pandas as pd
import akshare as ak
from pandas import read_pickle  # 仓库自身数据文件

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

adj = read_pickle(ROOT / "data/normalized_v2/adjusted_prices.pkl")
adj["date"] = pd.to_datetime(adj["date"])
cross_rows = []
for sym, inst in [("RB0", "RB"), ("T0", "T"), ("SC0", "SC")]:
    try:
        main = ak.futures_main_sina(symbol=sym)
    except Exception as exc:
        emit(f"{sym}: akshare 失败 {type(exc).__name__}: {str(exc)[:120]}")
        continue
    main["日期"] = pd.to_datetime(main["日期"])
    main = main.sort_values("日期").set_index("日期")
    a = adj[adj.instrument.eq(inst)].set_index("date")["adjusted_price"].sort_index()
    common = a.index.intersection(main.index)
    a_c = a.loc[common]; m_c = main.loc[common, "收盘价"]
    ra = a_c.pct_change().dropna(); rm = m_c.pct_change().dropna()
    both = pd.concat([ra, rm], axis=1, keys=["repo", "sina"]).dropna()
    corr = both["repo"].corr(both["sina"])
    sign_agree = float((both["repo"] * both["sina"] > 0).mean())
    a_n = a_c / a_c.iloc[0] * 100; m_n = m_c / m_c.iloc[0] * 100
    cross_rows.append({"sina_symbol": sym, "instrument": inst, "common_days": len(common),
                       "first": str(common.min().date()), "last": str(common.max().date()),
                       "daily_return_corr": round(corr, 4), "same_sign_days": round(sign_agree, 4),
                       "repo_norm_end": round(float(a_n.iloc[-1]), 2),
                       "sina_norm_end": round(float(m_n.iloc[-1]), 2),
                       "cum_gap_pct": round(float(a_n.iloc[-1] / m_n.iloc[-1] - 1) * 100, 2)})
    emit(f"{inst}: 共同日={len(common)} ({common.min().date()}..{common.max().date()}), "
         f"日收益相关={corr:.4f}, 同号率={sign_agree:.2%}, "
         f"归一化末端 repo={a_n.iloc[-1]:.1f} vs sina={m_n.iloc[-1]:.1f} (累计差 {a_n.iloc[-1]/m_n.iloc[-1]-1:+.2%})")
    both.to_csv(TMP / f"main_series_returns_{inst}.csv", encoding="utf-8-sig")
    time.sleep(1.0)

pd.DataFrame(cross_rows).to_csv(TMP / "main_series_crosscheck.csv", index=False, encoding="utf-8-sig")
(REPORTS / "T7b_sina_main_cross.md").write_text(
    "# T7b 新浪主力连续 vs 仓库 Panama 复权价（趋势级）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT7b DONE")
