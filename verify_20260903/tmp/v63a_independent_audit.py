# -*- coding: utf-8 -*-
"""v6.3a 结果独立审计（只读）。产出独立核对结论，不修改任何仓库文件。"""
import numpy as np
import pandas as pd

ROOT = r"D:\FiveSectorMomentum"
OUT = ROOT + r"\outputs\v6_3a_20260907_134158"
log = []
def emit(s=""):
    print(s); log.append(str(s))

# ---- A. 旧映射的到期日倒退过渡 ----
mapping = pd.read_pickle(ROOT + r"\data\normalized_v2\mapping.pkl")
meta = pd.read_pickle(ROOT + r"\data\normalized_v2\contract_meta.pkl")
exp = meta.drop_duplicates("ts_code").set_index("ts_code")["delist_date"]
o = mapping.sort_values(["instrument", "date"], kind="mergesort").copy()
o["expiry"] = o["contract"].map(exp)
o["prev_contract"] = o.groupby("instrument")["contract"].shift()
o["prev_expiry"] = o.groupby("instrument")["expiry"].shift()
changed = o["contract"].ne(o["prev_contract"])
back = o.loc[changed & o["expiry"].notna() & o["prev_expiry"].notna() & o["expiry"].lt(o["prev_expiry"])].copy()
emit(f"[A] 旧映射到期日倒退过渡数={len(back)}，涉及品种={sorted(back.instrument.unique())}")
if len(back):
    emit(back[["date", "instrument", "prev_contract", "contract", "prev_expiry", "expiry"]].to_string(index=False))

# ---- B. 修复映射的到期日倒退过渡 ----
cm = pd.read_pickle(ROOT + r"\data\v6_3a\mapping_corrected.pkl")
co = cm.sort_values(["instrument", "date"], kind="mergesort").copy()
co["expiry"] = co["contract"].map(exp)
co["prev_contract"] = co.groupby("instrument")["contract"].shift()
co["prev_expiry"] = co.groupby("instrument")["expiry"].shift()
cch = co["contract"].ne(co["prev_contract"])
cback = co.loc[cch & co["expiry"].notna() & co["prev_expiry"].notna() & co["expiry"].lt(co["prev_expiry"])]
emit(f"[B] 修复映射剩余到期日倒退过渡数={len(cback)}")

# ---- C. 修复事件因果性 ----
ev = pd.read_pickle(ROOT + r"\data\v6_3a\mapping_correction_events.pkl")
emit(f"[C] 修复事件行数={len(ev)}，品种={sorted(ev.instrument.unique())}，"
     f"used_future_data任真={bool(ev.used_future_data.any())}，"
     f"volume<=0={int((ev.accepted_volume<=0).sum())}，"
     f"close<=0={int((ev.accepted_close<=0).sum())}，"
     f"days<20={int((ev.accepted_days_to_expiry<20).sum())}")

# ---- D. 推荐否决项8：T01 vs G01 / T01 vs G02 三期点估计 ----
def load_eq(sid):
    e = pd.read_pickle(OUT + "\\" + sid + "\\daily_equity.pkl")
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values("date").reset_index(drop=True)
    return e

eq = {s: load_eq(s) for s in ["G01", "G02", "T01"]}
emit("[D] 期末权益  G01=%.2f  G02=%.2f  T01=%.2f" % (
    eq["G01"].equity.iloc[-1], eq["G02"].equity.iloc[-1], eq["T01"].equity.iloc[-1]))

def periods(d):
    full = d.index >= d.index[0]
    insample = d["date"] < pd.Timestamp("2022-01-01")
    val = d["date"] >= pd.Timestamp("2022-01-01")
    return full, insample, val

g01 = eq["G01"]; g02 = eq["G02"]; t01 = eq["T01"]
# align on common dates
common = g01.set_index("date").index.intersection(t01.set_index("date").index)
for a, b, name in [(g01, t01, "T01_minus_G01"), (g02, t01, "T01_minus_G02")]:
    aa = a.set_index("date").loc[common, "net_pnl"]
    bb = b.set_index("date").loc[common, "net_pnl"]
    full = bb.index >= bb.index[0]
    ins = bb.index < pd.Timestamp("2022-01-01")
    val = bb.index >= pd.Timestamp("2022-01-01")
    mean_full = float((bb[full] - aa[full]).mean())
    mean_ins = float((bb[ins] - aa[ins]).mean())
    mean_val = float((bb[val] - aa[val]).mean())
    emit(f"[D] {name}: 全样本日净pnl差均值={mean_full:.2e}  样本内={mean_ins:.2e}  验证期={mean_val:.2e}")

# ---- E. 账户勾稽独立复核（G01 与 T01）----
for sid in ["G01", "T01"]:
    e = eq[sid]
    inc = e["equity"].diff().dropna()
    npnl = e["net_pnl"].iloc[1:]
    err_inc = float((inc - npnl).abs().max())
    term = float(e["equity"].iloc[-1] - e["equity"].iloc[0] - e["net_pnl"].sum())
    emit(f"[E] {sid}: 逐日残差max={err_inc:.3e}  期末-累计残差={term:.3e}")

out = ROOT + r"\verify_20260903\tmp\v63a_independent_audit_report.txt"
open(out, "w", encoding="utf-8").write("\n".join(log))
emit("\nDONE -> " + out)
