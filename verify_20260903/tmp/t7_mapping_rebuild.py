# -*- coding: utf-8 -*-
"""T7 主力映射重建（最大 OI）+ 新浪主力连续交叉。rng=20260903。"""
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
mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])
basic = read_pickle(ROOT / "data/raw/tushare/fut_basic.pkl")
basic["list_date"] = pd.to_datetime(basic["list_date"], errors="coerce")
basic["delist_date"] = pd.to_datetime(basic["delist_date"], errors="coerce")
basic["fut_code_u"] = basic["fut_code"].astype(str).str.upper()
win = basic.drop_duplicates("ts_code").set_index("ts_code")[["list_date", "delist_date"]]

# fut_code(instrument) -> ts_code 集合：通过 daily.instrument 列直接给品种归属
by_inst_day = {}
for r in daily.itertuples(index=False):
    by_inst_day.setdefault((r.instrument, r.trade_date), []).append((r.ts_code, r.oi if pd.notna(r.oi) else 0.0))

rows = []
for inst, g in mapping.groupby("instrument"):
    for r in g.itertuples(index=False):
        cands = by_inst_day.get((inst, r.date))
        if not cands:
            rows.append({"instrument": inst, "date": r.date, "repo_contract": r.contract,
                         "my_maxoi_contract": None, "match": False, "repo_source": r.source})
            continue
        best = None; best_oi = -1
        for code, oi in cands:
            lw = win.loc[code] if code in win.index else None
            if lw is not None and pd.notna(lw.list_date) and r.date < lw.list_date:
                continue  # 上市前（数据不应出现，防御）
            if best is None or oi > best_oi:
                best, best_oi = code, oi
        rows.append({"instrument": inst, "date": r.date, "repo_contract": r.contract,
                     "my_maxoi_contract": best, "match": best == r.contract, "repo_source": r.source,
                     "my_oi": best_oi})
cmp = pd.DataFrame(rows)
cmp.to_csv(TMP / "mapping_diff_full.csv", index=False, encoding="utf-8-sig")
n_match = int(cmp["match"].sum())
emit(f"逐日映射对比: {n_match}/{len(cmp)} 一致 ({n_match/len(cmp)*100:.2f}%)")
mism = cmp[~cmp["match"].astype(bool)]
emit(f"不一致 {len(mism)} 天，按 repo_source 分组:")
emit(mism.groupby("repo_source").size().to_string())
emit("按品种分组(前10):")
emit(mism.groupby("instrument").size().sort_values(ascending=False).head(10).to_string())
mism_head = mism.sort_values(["instrument", "date"]).head(30)[["instrument","date","repo_contract","my_maxoi_contract","repo_source"]]
emit("\n不一致样例(前30):")
emit(mism_head.to_string(index=False))
mism.head(200).to_csv(TMP / "mapping_diff.csv", index=False, encoding="utf-8-sig")

# ---- 新浪主力连续交叉（趋势级） ----
adj = read_pickle(ROOT / "data/normalized_v2/adjusted_prices.pkl")
adj["date"] = pd.to_datetime(adj["date"])
cross_rows = []
for sym, inst in [("RB0", "RB"), ("T0", "T"), ("SC0", "SC")]:
    try:
        main = ak.futures_main_sina(symbol=sym)
    except Exception as exc:
        emit(f"{sym}: akshare 失败 {type(exc).__name__}: {str(exc)[:120]}")
        continue
    main["date"] = pd.to_datetime(main["date"])
    main = main.sort_values("date").set_index("date")
    a = adj[adj.instrument.eq(inst)].set_index("date")["adjusted_price"].sort_index()
    common = a.index.intersection(main.index)
    a_c = a.loc[common]; m_c = main.loc[common, "close"]
    ra = a_c.pct_change().dropna(); rm = m_c.pct_change().dropna()
    both = pd.concat([ra, rm], axis=1, keys=["repo", "sina"]).dropna()
    corr = both["repo"].corr(both["sina"])
    # 归一化水平（首日=100）末端对比
    a_n = a_c / a_c.iloc[0] * 100; m_n = m_c / m_c.iloc[0] * 100
    cross_rows.append({"sina_symbol": sym, "instrument": inst, "common_days": len(common),
                       "first": str(common.min().date()), "last": str(common.max().date()),
                       "daily_return_corr": round(corr, 4),
                       "repo_norm_end": round(float(a_n.iloc[-1]), 2),
                       "sina_norm_end": round(float(m_n.iloc[-1]), 2),
                       "cum_gap_pct": round(float(a_n.iloc[-1] / m_n.iloc[-1] - 1) * 100, 2)})
    emit(f"{inst}: 共同日={len(common)} ({common.min().date()}..{common.max().date()}), "
         f"日收益相关={corr:.4f}, 归一化末端 repo={a_n.iloc[-1]:.1f} vs sina={m_n.iloc[-1]:.1f} "
         f"(累计差 {a_n.iloc[-1]/m_n.iloc[-1]-1:+.2%})")
    both.to_csv(TMP / f"main_series_returns_{inst}.csv", encoding="utf-8-sig")
    time.sleep(1.0)

pd.DataFrame(cross_rows).to_csv(TMP / "main_series_crosscheck.csv", index=False, encoding="utf-8-sig")

(REPORTS / "T7_mapping_rebuild.md").write_text(
    "# T7 主力映射重建（最大OI）+ 新浪主力连续交叉\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT7 DONE")
