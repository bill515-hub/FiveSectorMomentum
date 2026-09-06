import pandas as pd

BASE = "D:/FiveSectorMomentum/outputs/v4_2_20260903_091241"
f = pd.read_pickle(f"{BASE}/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")

print("RB/SP fee_rate distinct in fills:")
for inst in ["RB", "SP"]:
    sub = f[f["instrument"].eq(inst)]
    print(f"  {inst}: n={len(sub)} fee_rate={sorted(sub['fee_rate'].round(8).unique())} "
          f"fee_per_lot={sorted(sub['fee_per_lot'].round(4).unique())}")

# groupby attribution without include_groups
def attr(g):
    frc = g["fee_rate"] * 10.0
    ex_corr = g["quantity"].abs() * (g["fee_per_lot"] + g["price"] * g["point_value"] * frc)
    return pd.Series({
        "orig_ex": g["exchange_commission"].sum(),
        "corr_ex": ex_corr.sum(),
        "delta": ex_corr.sum() - g["exchange_commission"].sum(),
    })

g = f.groupby("instrument").apply(attr, include_groups=False)
print("\nper-instrument exchange-commission attribution (top by |delta|):")
print(g.sort_values("delta", key=lambda s: s.abs(), ascending=False).to_string())

tot_orig_ex = f["exchange_commission"].sum()
frc = f["fee_rate"].where(~f["instrument"].isin(["RB", "SP"]), f["fee_rate"] * 10.0)
ex_corr = f["quantity"].abs() * (f["fee_per_lot"] + f["price"] * f["point_value"] * frc)
comm_corr = ex_corr * f["fee_multiplier"]
print(f"\nTOTALS: orig_ex={tot_orig_ex:.2f} corr_ex={ex_corr.sum():.2f} "
      f"orig_client={f['commission'].sum():.2f} corr_client={comm_corr.sum():.2f} "
      f"delta_client={comm_corr.sum()-f['commission'].sum():.2f}")
