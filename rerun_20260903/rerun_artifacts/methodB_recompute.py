"""R1 method B: independent post-hoc fee recompute on v4_2 S1/S2 fills.

Does NOT import the backtest engine. Pure pandas arithmetic.
Calibration gate: S1 sum(exchange_commission) must equal 3,998,744 (+-10)
before the corrected numbers are trusted.
"""
import pandas as pd

BASE = "D:/FiveSectorMomentum/outputs/v4_2_20260903_091241"
OUT = "D:/FiveSectorMomentum/rerun_20260903/rerun_artifacts"
AFFECTED = {"RB", "SP"}

rows = []
for sleeve in ["S1__strategy_sleeve_20skip5_250_equal_risk",
               "S2__strategy_sleeve_20skip5_250_equal_risk_fixed_3tick"]:
    f = pd.read_pickle(f"{BASE}/{sleeve}/fills.pkl")
    orig_ex = float(f["exchange_commission"].sum())
    orig_comm = float(f["commission"].sum())
    frc = f["fee_rate"].where(~f["instrument"].isin(AFFECTED), f["fee_rate"] * 10.0)
    ex_corr = (f["quantity"].abs() * (f["fee_per_lot"] + f["price"] * f["point_value"] * frc))
    comm_corr = ex_corr * f["fee_multiplier"]
    delta = float(ex_corr.sum() - f["exchange_commission"].sum())
    # per-instrument attribution
    f2 = f.copy()
    f2["ex_corr"] = ex_corr
    attr = (f2[f2["instrument"].isin(AFFECTED)]
            .groupby("instrument")
            .apply(lambda g: pd.Series({
                "orig_ex": g["exchange_commission"].sum(),
                "corr_ex": g["ex_corr"].sum(),
                "delta": g["ex_corr"].sum() - g["exchange_commission"].sum(),
            }), include_groups=False))
    rows.append({
        "sleeve": sleeve, "orig_exchange_commission": orig_ex,
        "corrected_exchange_commission": float(ex_corr.sum()),
        "delta_commission": delta,
        "orig_client_commission": orig_comm,
        "corrected_client_commission": float(comm_corr.sum()),
        "attribution": attr.to_dict(),
    })
    # save corrected fills for S1 only
    if sleeve.startswith("S1"):
        out = f[["date", "instrument", "quantity", "price", "point_value",
                 "fee_rate", "exchange_commission", "commission"]].copy()
        out["fee_rate_corrected"] = frc
        out["exchange_commission_corrected"] = ex_corr
        out["commission_corrected"] = comm_corr
        out.to_csv(f"{OUT}/methodB_S1_corrected_fills.csv", index=False, encoding="utf-8-sig")

for r in rows:
    print("=" * 70)
    for k, v in r.items():
        if k == "attribution":
            print(f"{k}:")
            for inst, d in v.items():
                print(f"    {inst}: orig={d['orig_ex']:.2f} corr={d['corr_ex']:.2f} delta={d['delta']:.2f}")
        else:
            print(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")

# calibration gate
s1 = rows[0]
gate_ok = abs(s1["orig_exchange_commission"] - 3_998_744.0) <= 10.0
print("=" * 70)
print("CALIBRATION GATE S1 orig exchange_commission == 3,998,744 ±10:", gate_ok, f"(got {s1['orig_exchange_commission']:.2f})")
accept = 1_390_000.0 <= s1["delta_commission"] <= 1_510_000.0
print("ACCEPT S1 delta ∈ [139万,151万]:", accept, f"(got {s1['delta_commission']:.2f})")
print("VERDICT:", "PASS" if (gate_ok and accept) else "NEEDS-EDITS")
