# -*- coding: utf-8 -*-
"""对 v6.3a 新增独立审计分析（180842 目录）的数值核验。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl，属受审计既有内容）。
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
AUD = ROOT / "outputs/v6_3a_independent_audit_20260907_180842"
RUN = ROOT / "outputs/v6_3a_20260907_134158"
TMP = ROOT / "verify_20260903" / "tmp"

log = []
def emit(s=""):
    print(s); log.append(str(s))

# ---------- 1. 相关性矩阵独立重建（核心3对 + G01~S07） ----------
scen = ["G01", "G02", "S03", "S07", "D01", "T01", "S01"]
rets = {}
for sid in scen:
    eq = read_pickle(RUN / sid / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
    prev = eq["equity"].shift(1).fillna(10_000_000.0)
    rets[sid] = pd.Series(eq["net_pnl"].to_numpy() / prev.to_numpy(), index=pd.DatetimeIndex(eq["date"]))
R = pd.DataFrame(rets)
emit(f"日收益矩阵: {R.shape}, 日期 {R.index.min().date()}..{R.index.max().date()}")
pairs = [("D01", "S03"), ("S03", "S07"), ("D01", "S07"), ("G01", "S07"), ("G01", "G02"), ("G02", "T01")]
for a, b in pairs:
    r = R[a].corr(R[b])
    emit(f"[日度Pearson] {a}~{b}: 我的计算={r:.4f}")

# 月度（几何复合）
M = (1 + R).resample("ME").prod() - 1
for a, b in [("D01", "S03"), ("S03", "S07"), ("D01", "S07"), ("G01", "S07")]:
    r = M[a].corr(M[b])
    emit(f"[月度Pearson] {a}~{b}: 我的计算={r:.4f} (n={M[a].notna().sum()})")

# 年度
Y = (1 + R).resample("YE").prod() - 1
Yc = Y[Y.index.year < 2026]
for a, b in [("G01", "S07"), ("G02", "T01")]:
    r = Yc[a].corr(Yc[b])
    emit(f"[年度Pearson完整年] {a}~{b}: 我的计算={r:.4f} (n={len(Yc)})")

# ---------- 2. Carver 指标独立复算（G02/T01/S03 三场景） ----------
import math
def carver_metrics(sid):
    r = R[sid].dropna()
    n = len(r)
    years = n / 256
    mean_annual = r.mean() * 256
    sd = r.std(ddof=1) * math.sqrt(256)
    sharpe = r.mean() / r.std(ddof=1) * 16
    wealth = (1 + r).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1
    avg_dd = dd.mean()
    # 月度复合收益偏度
    m = ((1 + r).resample("ME").prod() - 1).dropna()
    skew = float(m.skew())
    # 上下尾
    rm = r - r.mean()
    lower = (rm.quantile(0.01) / rm.quantile(0.30)) / 4.43
    upper = (rm.quantile(0.99) / rm.quantile(0.70)) / 4.43
    return dict(years=years, mean_annual=mean_annual, avg_dd=avg_dd, sd=sd, sharpe=sharpe,
                skew=skew, lower=lower, upper=upper)
for sid in ["G02", "T01", "S03"]:
    c = carver_metrics(sid)
    emit(f"[Carver复算] {sid}: years={c['years']:.3f}, mean_annual={c['mean_annual']:.4f}, "
         f"avg_dd={c['avg_dd']:.4f}, sd={c['sd']:.4f}, sharpe={c['sharpe']:.4f}, "
         f"skew={c['skew']:.4f}, lower={c['lower']:.4f}, upper={c['upper']:.4f}")

pc = read_pickle(AUD / "performance_characteristics_all.pkl")
pc.columns = [c.lower() for c in pc.columns]
for sid in ["G02", "T01", "S03"]:
    row = pc[pc.scenario_id.eq(sid)]
    if len(row):
        r = row.iloc[0]
        emit(f"[Carver报告值] {sid}: years={r['carver_years_of_data_256']:.3f}, "
             f"mean_annual={r['carver_mean_annual_return_256']:.4f}, avg_dd={r['carver_average_drawdown']:.4f}, "
             f"sd={r['carver_annualized_standard_deviation_256']:.4f}, sharpe={r['carver_sharpe_256']:.4f}, "
             f"skew={r['carver_monthly_skew']:.4f}, lower={r['carver_lower_tail']:.4f}, upper={r['carver_upper_tail']:.4f}")

# ---------- 3. WY step-down 表核验：点估计与 HAC SE ----------
wy = read_pickle(AUD / "audited_westfall_young_stepdown.pkl")
wy.columns = [c.lower() for c in wy.columns]
for _, row in wy.iterrows():
    emit(f"[WY] {row['phase']} {row['hypothesis']}: mean_diff={row['observed_mean_daily_difference']:+.5f}, "
         f"HAC_SE={row['hac_standard_error']:.5f}, |t|={row['observed_abs_t']:.3f}, "
         f"p_adj={row['stepdown_adjusted_p']:.4f}")

# 独立计算 T01-G02 验证期 HAC lag19 SE 与 t
val = R[R.index >= "2022-01-01"]
d = (val["T01"] - val["G02"]).dropna()
n = len(d)
dm = d - d.mean()
g0 = (dm * dm).sum() / n
hac_var = g0
for lag in range(1, 20):
    g = (dm.iloc[lag:] * dm.iloc[:-lag].to_numpy()).sum() / n
    hac_var += 2 * (1 - lag / 20) * g
se = math.sqrt(hac_var)
t_obs = d.mean() / se * math.sqrt(n)
emit(f"[WY独立复算] validation T01-G02: n={n}, mean={d.mean():+.5f}, HAC19_SE={se:.5f}, t={t_obs:.3f}")

# full 样本 T01-G01
d2 = (R["T01"] - R["G01"]).dropna()
n2 = len(d2)
dm2 = d2 - d2.mean()
hv2 = (dm2 * dm2).sum() / n2
for lag in range(1, 20):
    g = (dm2.iloc[lag:] * dm2.iloc[:-lag].to_numpy()).sum() / n2
    hv2 += 2 * (1 - lag / 20) * g
se2 = math.sqrt(hv2)
emit(f"[WY独立复算] full T01-G01: n={n2}, mean={d2.mean():+.5f}, HAC19_SE={se2:.5f}, t={d2.mean()/se2*math.sqrt(n2):.3f}")

# ---------- 4. A05 基座配置哈希 ----------
import hashlib
p = ROOT / "configs/five_sector_momentum_v4_2_repaired.yaml"
h = hashlib.sha256(p.read_bytes()).hexdigest()
emit(f"\n[A05] v4_2_repaired.yaml 当前SHA-256={h}")
emit(f"[A05] 声明值=45c373b25c49d742a44ccbc971dd703a89b7926ca0faeb3ed819e65fef7030bd")
emit(f"[A05] 一致={h == '45c373b25c49d742a44ccbc971dd703a89b7926ca0faeb3ed819e65fef7030bd'}")

# ---------- 5. G01~S07 差异是否真实（结算核对） ----------
eq_g = read_pickle(RUN / "G01" / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
eq_s = read_pickle(RUN / "S07" / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
emit(f"\n[G01/S07] 期末权益 G01={eq_g.equity.iloc[-1]:,.0f}, S07={eq_s.equity.iloc[-1]:,.0f}, "
     f"差={eq_g.equity.iloc[-1]-eq_s.equity.iloc[-1]:+,.0f}")

(TMP / "v63a_analysis_audit_report.txt").write_text("\n".join(log), encoding="utf-8")
emit("\nDONE")
