import pandas as pd

BASE = "D:/FiveSectorMomentum/outputs/v4_2_20260903_091241"
f = pd.read_pickle(f"{BASE}/S2__strategy_sleeve_20skip5_250_equal_risk_fixed_3tick/fills.pkl")

print("S2 rows:", len(f))
print("fee_multiplier distinct:", sorted(f["fee_multiplier"].round(4).unique()))
print("RB/SP fee_rate distinct:", end=" ")
for inst in ["RB", "SP"]:
    sub = f[f["instrument"].eq(inst)]
    print(f"{inst}={sorted(sub['fee_rate'].round(8).unique())}", end="  ")
print()

frc = f["fee_rate"].where(~f["instrument"].isin(["RB", "SP"]), f["fee_rate"] * 10.0)
ex_corr = f["quantity"].abs() * (f["fee_per_lot"] + f["price"] * f["point_value"] * frc)
comm_corr = ex_corr * f["fee_multiplier"]

print(f"S2 orig_exchange={f['exchange_commission'].sum():.2f}")
print(f"S2 corr_exchange={ex_corr.sum():.2f}")
print(f"S2 delta_exchange={ex_corr.sum()-f['exchange_commission'].sum():.2f}")
print(f"S2 orig_client={f['commission'].sum():.2f}")
print(f"S2 corr_client={comm_corr.sum():.2f}")
print(f"S2 delta_client={comm_corr.sum()-f['commission'].sum():.2f}")

# per-instrument RB/SP attribution
for inst in ["RB", "SP"]:
    g = f[f["instrument"].eq(inst)]
    gc = frc[f["instrument"].eq(inst)]
    exg = g["quantity"].abs() * (g["fee_per_lot"] + g["price"] * g["point_value"] * gc)
    print(f"  {inst}: orig_ex={g['exchange_commission'].sum():.2f} "
          f"corr_ex={exg.sum():.2f} delta={exg.sum()-g['exchange_commission'].sum():.2f}")
