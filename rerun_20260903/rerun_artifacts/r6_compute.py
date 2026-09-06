"""R6 verification: quantify validation-period winner selection bias (read-only).

Reads v4/v4_1/v4_2 outputs; writes only summary JSON under rerun_artifacts.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
V4 = ROOT / "outputs" / "v4_20260902_102628"
V41 = ROOT / "outputs" / "v4_1_20260902_163841"
OUT = ROOT / "rerun_20260903" / "rerun_artifacts"

CANDIDATES = [
    "single_20", "single_60", "single_120", "single_180", "single_250",
    "single_20_skip5", "single_60_skip5", "single_120_skip5",
    "single_180_skip5", "single_250_skip5", "single_250_minus_20",
    "multi_fast_raw", "multi_all_raw", "multi_slow_raw",
    "multi_fast_scaled", "multi_all_scaled", "multi_slow_scaled",
]
REFERENCE = "reference_v3_252"
SLEEVES = [
    "strategy_sleeve_fast_equal_risk",
    "strategy_sleeve_all_equal_risk",
    "strategy_sleeve_slow_equal_risk",
]
ALL21 = [REFERENCE] + CANDIDATES + SLEEVES
WINNER = "single_180_skip5"

# ---- 1. point-estimate validation metrics for the 21 base strategies ----
sm = pd.read_csv(V4 / "scenario_metrics_v4.csv")
sm = sm[sm["标签"].isin([REFERENCE] + CANDIDATES)].copy()
base = sm[["标签", "验证期年化收益率", "验证期夏普比率", "验证期最大回撤", "验证期Calmar比率"]].rename(
    columns={"标签": "strategy", "验证期年化收益率": "cagr", "验证期夏普比率": "sharpe",
             "验证期最大回撤": "mdd", "验证期Calmar比率": "calmar"}
)

sl = pd.read_csv(V41 / "sleeve_metrics_v4_1.csv")
sl = sl[(sl["strategy"].isin(SLEEVES)) & (sl["cost_code"] == "C3") & (sl["period"] == "validation")].copy()
sl = sl[["strategy", "年化收益率", "夏普比率", "最大回撤", "Calmar比率"]].rename(
    columns={"年化收益率": "cagr", "夏普比率": "sharpe", "最大回撤": "mdd", "Calmar比率": "calmar"}
)

df = pd.concat([base, sl], ignore_index=True)
assert set(df["strategy"]) == set(ALL21), set(ALL21) - set(df["strategy"])
df = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
df["rank_sharpe"] = df["sharpe"].rank(ascending=False, method="min").astype(int)
df["rank_cagr"] = df["cagr"].rank(ascending=False, method="min").astype(int)

winner_row = df.loc[df["strategy"] == WINNER].iloc[0]
med_sharpe = float(df["sharpe"].median())
mean_sharpe = float(df["sharpe"].mean())
sd_sharpe = float(df["sharpe"].std(ddof=1))
med_cagr = float(df["cagr"].median())
mean_cagr = float(df["cagr"].mean())
max_sharpe = float(df["sharpe"].max())
max_cagr = float(df["cagr"].max())

# standardized gap under the null that the 21 are iid with the same cross-sectional
# mean/sd (classic multiple-comparison reference): E[max of n standard normals]
rng = np.random.default_rng(20260902)
n = len(df)
m = 200_000
null_max = rng.standard_normal((m, n)).max(axis=1)
expected_null_max = float(null_max.mean())
null_max_q95 = float(np.quantile(null_max, 0.95))
z_winner = (float(winner_row["sharpe"]) - mean_sharpe) / sd_sharpe
z_max = (max_sharpe - mean_sharpe) / sd_sharpe

point_estimate = {
    "n": n,
    "winner": WINNER,
    "winner_validation_sharpe": float(winner_row["sharpe"]),
    "winner_validation_cagr": float(winner_row["cagr"]),
    "winner_validation_mdd": float(winner_row["mdd"]),
    "winner_rank_sharpe_of_21": int(winner_row["rank_sharpe"]),
    "winner_rank_cagr_of_21": int(winner_row["rank_cagr"]),
    "median_sharpe": med_sharpe,
    "mean_sharpe": mean_sharpe,
    "sd_sharpe": sd_sharpe,
    "median_cagr": med_cagr,
    "mean_cagr": mean_cagr,
    "winner_excess_sharpe_over_median": float(winner_row["sharpe"]) - med_sharpe,
    "winner_excess_sharpe_over_mean": float(winner_row["sharpe"]) - mean_sharpe,
    "winner_excess_cagr_over_median": float(winner_row["cagr"]) - med_cagr,
    "winner_excess_cagr_over_mean": float(winner_row["cagr"]) - mean_cagr,
    "max_sharpe_strategy": str(df.loc[df["sharpe"].idxmax(), "strategy"]),
    "max_sharpe": max_sharpe,
    "max_cagr_strategy": str(df.loc[df["cagr"].idxmax(), "strategy"]),
    "max_cagr": max_cagr,
    "z_winner": z_winner,
    "z_max": z_max,
    "expected_null_max_of_21": expected_null_max,
    "null_max_q95": null_max_q95,
}

# ---- 2. joint block bootstrap: winner vs cross-sectional median gap ----
bd = pd.read_csv(V41 / "bootstrap_strategy_draws_v4_1.csv")
bd = bd[(bd["phase"] == "validation") & (bd["basis"] == "net")].copy()
piv = bd.pivot_table(index="repeat", columns="strategy", values="sharpe")
assert set(piv.columns) == set(ALL21), set(ALL21) - set(piv.columns)
rep = piv.index.nunique()
med = piv.median(axis=1)
winner_gap = piv[WINNER] - med
winner_rank = piv.rank(axis=1, ascending=False)[WINNER]
champion_gap = piv.max(axis=1) - med

bootstrap = {
    "repetitions": int(rep),
    "winner_sharpe_mean": float(piv[WINNER].mean()),
    "winner_sharpe_median": float(piv[WINNER].median()),
    "winner_sharpe_q05": float(piv[WINNER].quantile(0.05)),
    "winner_sharpe_q95": float(piv[WINNER].quantile(0.95)),
    "winner_minus_median_mean": float(winner_gap.mean()),
    "winner_minus_median_median": float(winner_gap.median()),
    "winner_minus_median_q05": float(winner_gap.quantile(0.05)),
    "winner_minus_median_q95": float(winner_gap.quantile(0.95)),
    "winner_above_median_freq": float((winner_gap > 0).mean()),
    "winner_mean_rank": float(winner_rank.mean()),
    "winner_median_rank": float(winner_rank.median()),
    "champion_minus_median_mean": float(champion_gap.mean()),
    "champion_minus_median_median": float(champion_gap.median()),
}

summary = {"point_estimate": point_estimate, "bootstrap": bootstrap, "table": df.to_dict(orient="records")}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "r6_compute.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary["point_estimate"], ensure_ascii=False, indent=2))
print(json.dumps(summary["bootstrap"], ensure_ascii=False, indent=2))
print("\n--- 21-strategy validation table (net) ---")
print(df[["strategy", "rank_sharpe", "sharpe", "cagr", "mdd", "rank_cagr"]].to_string(index=False))
