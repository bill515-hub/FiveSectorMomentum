# -*- coding: utf-8 -*-
"""T3 保证金敏感性（离线）。四场景逐日占用 vs 0.65/0.78 约束。

信任边界：仅反序列化仓库自身数据文件（.pkl，已入 pre_manifest 哈希快照）。
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
settle_map = {}
for r in daily.itertuples(index=False):
    mark = r.settle if (pd.notna(r.settle) and r.settle > 0) else r.close
    settle_map[(r.trade_date, r.ts_code)] = (mark, r.vol)

meta = read_pickle(ROOT / "data/normalized_v2/contract_meta.pkl")
pv_map = dict(zip(meta["ts_code"], meta["point_value"]))
fb_map = dict(zip(meta["ts_code"], meta["fallback_margin_rate"]))
EXEMPT = {"T"}  # configs: leverage_exempt_sectors=[government_bond]，该板块唯一品种 T

fee = read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
fee["trade_date"] = pd.to_datetime(fee["trade_date"], errors="coerce")
fee = fee[fee["source_status"].eq("tushare")]
n_rate_nonnull = int(fee["long_margin_rate"].notna().sum())
emit(f"fee raw usable rows={len(fee)}, long_margin_rate 非空={n_rate_nonnull}")
rate_map = {}
for r in fee.itertuples(index=False):
    if pd.isna(r.trade_date):
        continue
    rate_map[(r.ts_code, r.trade_date)] = (r.long_margin_rate, r.short_margin_rate)

def scenario_margins(pos_frame):
    """返回逐日 dict(date -> (total_margin, commodity_margin, fallback_used)) 按 4 场景。"""
    scen = {"S0_fallback": {}, "S1_fb1p5": {}, "S2_fb2p0": {}, "S3_real": {}}
    fb_used = {"S3_real": 0}
    rows_total = 0
    for (date, grp) in pos_frame.groupby("date"):
        rows_total += len(grp)
        acc = {k: 0.0 for k in scen}
        acc_comm = {k: 0.0 for k in scen}
        for r in grp.itertuples(index=False):
            skey = (r.date, r.contract)   # 结算表键序：(trade_date, ts_code)
            rkey = (r.contract, r.date)   # 费率表键序：(ts_code, trade_date)
            mark, _ = settle_map.get(skey, (np.nan, np.nan))
            pv = pv_map.get(r.contract, np.nan)
            fb = fb_map.get(r.contract, 0.18)
            notional = abs(r.position) * mark * pv
            is_comm = r.instrument not in EXEMPT
            rates = {
                "S0_fallback": fb,
                "S1_fb1p5": fb * 1.5,
                "S2_fb2p0": fb * 2.0,
            }
            lr, sr = rate_map.get(rkey, (np.nan, np.nan))
            real = sr if r.position < 0 else lr
            if pd.notna(real) and real > 0:
                if real > 1.0:
                    # CFFEX(T) 字段为百分数表示（如 2.0 = 2%），与小数品种并存，统一归一为小数
                    real = real / 100.0
            else:
                real = fb
                fb_used["S3_real"] += 1
            rates["S3_real"] = real
            for k, rate in rates.items():
                m = notional * rate * 1.25
                acc[k] += m
                if is_comm:
                    acc_comm[k] += m
        for k in scen:
            scen[k][date] = (acc[k], acc_comm[k])
    return scen, fb_used, rows_total

for label, root_dir in [("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline"),
                        ("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk")]:
    pos = read_pickle(root_dir / "positions.pkl")
    pos["date"] = pd.to_datetime(pos["date"])
    eq = read_pickle(root_dir / "daily_equity.pkl")
    eq["date"] = pd.to_datetime(eq["date"])
    equity_by_date = dict(zip(eq["date"], eq["equity"]))

    scen, fb_used, n_pos_rows = scenario_margins(pos)
    emit(f"\n===== {label}: positions行={n_pos_rows}, S3缺真实率回退fallback 次数={fb_used['S3_real']} =====")

    # ---- S0 校验：与记录值比对 ----
    rec_total = dict(zip(eq["date"], eq["margin"]))
    rec_comm = dict(zip(eq["date"], eq["commodity_margin"]))
    d_total = []
    d_comm = []
    for d, (t, c) in scen["S0_fallback"].items():
        if d in rec_total:
            d_total.append(abs(t - float(rec_total[d])))
            d_comm.append(abs(c - float(rec_comm[d])))
    emit(f"[S0校验] vs 记录margin: max|diff|={max(d_total):.6f} 元; vs commodity_margin: max|diff|={max(d_comm):.6f} 元 "
         f"(天数={len(d_total)})")

    # ---- 各场景占用 vs 约束 ----
    out_rows = []
    for k in ["S0_fallback", "S1_fb1p5", "S2_fb2p0", "S3_real"]:
        comm_breach = []
        total_breach = []
        peaks_comm = 0.0; peaks_total = 0.0
        for d, (t, c) in sorted(scen[k].items()):
            e = float(equity_by_date.get(d, np.nan))
            if not np.isfinite(e):
                continue
            cu = c / e; tu = t / e
            peaks_comm = max(peaks_comm, cu); peaks_total = max(peaks_total, tu)
            if cu > 0.65:
                comm_breach.append((d, cu))
            if tu > 0.78:
                total_breach.append((d, tu))
        out_rows.append({
            "run": label, "scenario": k,
            "comm_breach_days(>0.65)": len(comm_breach),
            "comm_peak_utilization": round(peaks_comm, 4),
            "comm_breach_first": str(comm_breach[0][0].date()) if comm_breach else "",
            "comm_breach_last": str(comm_breach[-1][0].date()) if comm_breach else "",
            "total_breach_days(>0.78)": len(total_breach),
            "total_peak_utilization": round(peaks_total, 4),
            "total_breach_first": str(total_breach[0][0].date()) if total_breach else "",
            "total_breach_last": str(total_breach[-1][0].date()) if total_breach else "",
        })
        emit(f"[{k}] 商品>0.65天数={len(comm_breach)} 峰值={peaks_comm:.4f}; "
             f"总>0.78天数={len(total_breach)} 峰值={peaks_total:.4f}")
        bd = pd.DataFrame(comm_breach + total_breach, columns=["date", "util"])
        if len(bd):
            bd["kind"] = ["comm"] * len(comm_breach) + ["total"] * len(total_breach)
            bd["scenario"] = k
            bd.to_csv(TMP / f"margin_breach_{label}_{k}.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame(out_rows).to_csv(TMP / "margin_scenario_utilization.csv", index=False, encoding="utf-8-sig", mode="a",
                                  header=not (TMP / "margin_scenario_utilization.csv").exists())

(REPORTS / "T3_margin_sensitivity.md").write_text(
    "# T3 保证金敏感性（S0 校验 + 四场景约束触发）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT3 DONE")
