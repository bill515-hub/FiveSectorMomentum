import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "outputs" / "v4_2_20260903_091241"
ART = ROOT / "rerun_20260903" / "rerun_artifacts"

def outer(left, right, keys):
    l = left.copy(); r = right.copy()
    for c in keys:
        if "date" in c:
            if c in l.columns:
                l[c] = pd.to_datetime(l[c], format="mixed")
            if c in r.columns:
                r[c] = pd.to_datetime(r[c], format="mixed")
    m = l.merge(r, on=keys, how="outer", indicator=True)
    return m["_merge"].value_counts().to_dict()

print("== scores outer-merge row counts ==")
for label, mine in [
    ("G1__single_20_skip5", "r4_recomputed_G1_scores.csv"),
    ("G2__single_250", "r4_recomputed_G2_scores.csv"),
    ("S1__strategy_sleeve_20skip5_250_equal_risk", "r4_recomputed_S1_scores.csv"),
]:
    r = pd.read_pickle(OUT / label / "scores.pkl")
    m = pd.read_csv(ART / mine)
    print(label, "my", len(m), "rec", len(r), outer(m, r, ["date", "instrument"]))

print("== selections outer-merge row counts ==")
for label, mine in [
    ("G1__single_20_skip5", "r4_recomputed_G1_selections.csv"),
    ("G2__single_250", "r4_recomputed_G2_selections.csv"),
    ("S1__strategy_sleeve_20skip5_250_equal_risk", "r4_recomputed_S1_selections.csv"),
]:
    r = pd.read_pickle(OUT / label / "selections.pkl")
    m = pd.read_csv(ART / mine)
    keys = ["signal_date", "sector", "instrument", "role"] + (["horizon"] if "horizon" in r.columns else [])
    print(label, "my", len(m), "rec", len(r), outer(m, r, keys))
    print("  weekly signal dates: my", m.signal_date.nunique(), "rec", r.signal_date.nunique())

print("== sign agreement denominators (defined pairs) ==")
for label, mine in [
    ("G1__single_20_skip5", "r4_recomputed_G1_scores.csv"),
    ("G2__single_250", "r4_recomputed_G2_scores.csv"),
    ("S1__strategy_sleeve_20skip5_250_equal_risk", "r4_recomputed_S1_scores.csv"),
]:
    r = pd.read_pickle(OUT / label / "scores.pkl")
    m = pd.read_csv(ART / mine)
    m["date"] = pd.to_datetime(m["date"]); r["date"] = pd.to_datetime(r["date"])
    j = m.merge(r, on=["date", "instrument"], suffixes=("_m", "_r"))
    both = j.score_m.notna() & j.score_r.notna()
    agree = (np.sign(j.loc[both, "score_m"]) == np.sign(j.loc[both, "score_r"])).sum()
    print(label, "defined", int(both.sum()), "sign_agree", int(agree),
          "rate", agree / both.sum() if both.sum() else np.nan)

print("== targets outer-merge ==")
r = pd.read_pickle(OUT / "S1__strategy_sleeve_20skip5_250_equal_risk" / "targets.pkl")
m = pd.read_csv(ART / "r4_recomputed_S1_targets.csv")
print("my", len(m), "rec", len(r), outer(m, r, ["date", "contract"]))

print("== internal/net/risk outer-merge ==")
for name, mine in [("internal_targets", "r4_recomputed_S1_internal_targets.csv"),
                   ("net_target_stages", "r4_recomputed_S1_net_target_stages.csv"),
                   ("risk_stages", "r4_recomputed_S1_risk_stages.csv")]:
    r = pd.read_pickle(OUT / "S1__strategy_sleeve_20skip5_250_equal_risk" / f"{name}.pkl")
    m = pd.read_csv(ART / mine)
    if name == "internal_targets":
        keys = ["date", "horizon", "sector"]
    elif name == "net_target_stages":
        keys = ["date", "contract"]
    else:
        keys = ["date"]
    print(name, "my", len(m), "rec", len(r), outer(m, r, keys))
