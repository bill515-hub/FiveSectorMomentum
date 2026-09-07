# -*- coding: utf-8 -*-
"""独立复核 v6_3a_independent_audit_20260907_180842 的新分析是否准确（只读）。"""
import numpy as np
import pandas as pd

ROOT = r"D:\FiveSectorMomentum"
MAIN = ROOT + r"\outputs\v6_3a_20260907_134158"
NEW = ROOT + r"\outputs\v6_3a_independent_audit_20260907_180842"
log = []
def emit(s=""):
    print(s); log.append(str(s))

def load_eq(sid, root=MAIN):
    e = pd.read_pickle(root + "\\" + sid + "\\daily_equity.pkl")
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values("date").reset_index(drop=True)
    e["ret"] = e["net_pnl"] / e["equity"].shift(1)
    return e

eq = {s: load_eq(s) for s in ["G01", "G02", "S03", "S07", "D01", "T01"]}

# ---- A. 年度几何收益复核（对照 annual_returns_all.csv）----
def annual(e):
    e = e.copy()
    e["year"] = e["date"].dt.year
    out = {}
    for y, g in e.groupby("year"):
        # 该年第一个交易日相对上一年的几何复合
        r = (1.0 + g["ret"]).prod() - 1.0
        out[y] = r
    return out

for sid, expected_list in {
    "G01": [(2016, -0.20053977665409228), (2018, 0.027534452726993175), (2024, 0.6157054191928382)],
    "S07": [(2018, 0.2543320506851443)],
    "G02": [(2020, 1.5467728083393224)],
}.items():
    a = annual(eq[sid])
    for yy, exp in expected_list:
        got = a[yy]
        emit(f"[A] {sid} {yy} 年收益 复核={got:.6f} 表={exp:.6f} 差={abs(got-exp):.2e}")

# ---- B. 日度Pearson相关复核（对照 correlation_pairwise_detail.csv）----
def daily_corr(a, b):
    common = a.set_index("date").index.intersection(b.set_index("date").index)
    ra = a.set_index("date").loc[common, "ret"]
    rb = b.set_index("date").loc[common, "ret"]
    return float(ra.corr(rb)), float(ra.corr(rb, method="spearman")), len(common)

for (a, b, exp_p, exp_s) in [
    ("G01", "S07", 0.9644387607863307, 0.9576066616789651),
    ("D01", "S07", 0.3370, None),          # 对照原 correlation_summary 20skip5-250
    ("D01", "S03", 0.5261, None),
    ("S03", "S07", 0.4814, None),
    ("G02", "T01", 0.9233289619057188, 0.9135322008757643),
]:
    p, s, n = daily_corr(eq[a], eq[b])
    emit(f"[B] {a}-{b} Pearson={p:.4f} (表={exp_p:.4f}) n={n}" + (f" Spearman={s:.4f} (表={exp_s:.4f})" if exp_s else ""))

# ---- C. HAC(19)标准误与t复核（对照 audited_westfall_young_stepdown.csv 验证期 T01-G02）----
t01 = eq["T01"]; g02 = eq["G02"]
common = t01.set_index("date").index.intersection(g02.set_index("date").index)
ra = t01.set_index("date").loc[common, "ret"]
rb = g02.set_index("date").loc[common, "ret"]
val = (ra.index >= pd.Timestamp("2022-01-01"))
d = (ra[val] - rb[val]).values
T = len(d)
x = d - d.mean()
L = 19
def nw_se(x, L):
    T = len(x)
    x = x - x.mean()
    gamma = np.array([(x[j:] * x[:T-j]).sum() / T for j in range(L+1)])
    w = 1.0 - np.arange(L+1) / (L+1)
    S = gamma[0] + 2.0 * (w[1:] * gamma[1:]).sum()
    return float(np.sqrt(S / T))
se = nw_se(x, L)
tstat = abs(d.mean()) / se
emit(f"[C] 验证期 T01-G02: n={T} mean={d.mean():.6e} HAC({L})SE={se:.6e} (表=2.131785590685e-04) |t|={tstat:.4f} (表=1.9294866)")

out = ROOT + r"\verify_20260903\tmp\v63a_newanalysis_audit.txt"
open(out, "w", encoding="utf-8").write("\n".join(log))
emit("\nDONE -> " + out)
