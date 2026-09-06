import pandas as pd, numpy as np, json
from pathlib import Path
ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT/"outputs"/"v4_2_20260903_091241"
ART = ROOT/"rerun_20260903"/"rerun_artifacts"

def price_diff_sharpe(changes, window, skip):
    usable = changes.shift(skip)
    mean = usable.rolling(window, min_periods=window).mean()
    std = usable.rolling(window, min_periods=window).std(ddof=1)
    return mean.divide(std.replace(0.0, np.nan)) * np.sqrt(252.0)

def wide_to_long(frame, value_name):
    return frame.rename_axis(index="date", columns="instrument").stack(future_stack=True).rename(value_name).reset_index()

adjusted = pd.read_pickle(ROOT/"data"/"normalized_v2"/"adjusted_prices.pkl")
prices = adjusted.pivot(index="date", columns="instrument", values="adjusted_price").sort_index()
changes = prices.diff()
s20 = price_diff_sharpe(changes, 20, 5)
s250 = price_diff_sharpe(changes, 250, 0)
# combined sleeve score
b20 = wide_to_long(s20, "score")
b250 = wide_to_long(s250, "score")
cf20 = b20.set_index(["date","instrument"])["score"].rename("single_20_skip5")
cf250 = b250.set_index(["date","instrument"])["score"].rename("single_250")
mine = pd.concat([cf20, cf250], axis=1).mean(axis=1).rename("score").reset_index()

rec = pd.read_pickle(OUT/"S1__strategy_sleeve_20skip5_250_equal_risk"/"scores.pkl")
j = mine.merge(rec, on=["date","instrument"], how="outer", indicator=True, suffixes=("_m","_r"))
both = j[j["_merge"]=="both"].copy()
d = (both["score_m"]-both["score_r"]).abs()
print("both rows:", len(both), "maxdiff:", d.max(), "exact(<1e-12):", (d<1e-12).sum())
mask = both["score_m"].notna() & both["score_r"].notna() & (both["score_r"]!=0)
sub = both[mask]
sm = np.sign(sub["score_m"]); sr = np.sign(sub["score_r"])
print("comparable:", len(sub), "sign agree:", (sm==sr).sum(), "disagree:", (sm!=sr).sum())
print("rate:", (sm==sr).sum()/len(sub))
# where do they disagree?
dis = sub[sm!=sr]
print("disagree sample:")
print(dis.head(20).to_string())
# check if disagree rows actually have score_m != score_r
print("disagree rows where score_m!=score_r:", (dis["score_m"]!=dis["score_r"]).sum(), "of", len(dis))
print("score_m range in disagree:", dis["score_m"].min(), dis["score_m"].max())
print("score_r range in disagree:", dis["score_r"].min(), dis["score_r"].max())
