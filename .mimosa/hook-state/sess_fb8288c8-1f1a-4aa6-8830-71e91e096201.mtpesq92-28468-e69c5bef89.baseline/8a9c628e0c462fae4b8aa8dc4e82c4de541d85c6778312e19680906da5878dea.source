"""Diagnose locked-day counts under different scopes to pin the ground truth.

Ground truth from the auditor:
  - MAIN-MAPPED contract days with high==low & vol>0  => 12 days
  - full scope (any contract) additionally surfaces RU2505 2025-04-07 old-leg
    limit-down sell (a contract that is held during a roll but not the current
    mapped contract on that date).

The earlier buggy derive_limit_prices.py applied high==low & vol>0 to ALL
contracts and got 16902 "locked" days.  The fix is to scope limit-price
derivation to contracts the engine can actually hold:
  (a) every contract that is the mapped main contract for some date, and
  (b) the previous-leg contract on roll days (already covered by (a) since it
      was mapped up to the roll date).

This script only REPORTS counts; it does not mutate bars.pkl.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

root = Path("data/normalized_v2")
bars = pd.read_pickle(root / "bars.pkl")
mapping = pd.read_pickle(root / "mapping.pkl")

bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
locked = (bars["high"] == bars["low"]) & (bars["volume"] > 0)
up = locked & (bars["settlement"] > bars["pre_settle"])
down = locked & (bars["settlement"] < bars["pre_settle"])

print("== all contracts (buggy scope) ==")
print("bars total:", len(bars))
print("locked:", int(locked.sum()), "up:", int(up.sum()), "down:", int(down.sum()))

# mapped contract per (date, instrument)
mapping["date"] = pd.to_datetime(mapping["date"])
mapped_keys = set(zip(mapping["date"], mapping["contract"]))

# contracts ever mapped (any date) -> all their bars are tradeable history
ever_mapped = set(mapping["contract"])
bars["is_ever_mapped"] = bars["ts_code"].isin(ever_mapped)

print()
print("== ever-mapped contracts (engine-tradeable history) ==")
em = bars["is_ever_mapped"]
print("bars:", int(em.sum()))
print("locked:", int((locked & em).sum()),
      "up:", int((up & em).sum()), "down:", int((down & em).sum()))

# current-mapped contract only on each (date, ts_code)
bars["is_current_mapped"] = list(zip(bars["date"], bars["ts_code"]))  # placeholder
bars = bars.drop(columns=["is_current_mapped"])
bars["_mapped_this_date"] = [
    (d, c) in mapped_keys for d, c in zip(bars["date"], bars["ts_code"])
]
cm = bars["_mapped_this_date"]
print()
print("== current-mapped bars only ==")
print("bars:", int(cm.sum()))
print("locked:", int((locked & cm).sum()),
      "up:", int((up & cm).sum()), "down:", int((down & cm).sum()))

print()
print("== current-mapped locked days (detail) ==")
detail = bars[locked & cm][
    ["ts_code", "date", "pre_settle", "open", "high", "low", "settlement", "volume"]
].sort_values("date")
print(detail.to_string())

print()
print("== ever-mapped locked days NOT current-mapped (roll old-legs) ==")
extra = bars[locked & em & ~cm][
    ["ts_code", "date", "pre_settle", "open", "high", "low", "settlement", "volume"]
].sort_values("date")
print(extra.to_string())
print("extra count:", len(extra))

# Confirm RU2505 2025-04-07 old-leg limit-down row
print()
print("== RU2505 around 2025-04-07 ==")
ru = bars[(bars["ts_code"] == "RU2505.SHF") &
          (bars["date"].between("2025-04-01", "2025-04-10"))][
    ["ts_code", "date", "pre_settle", "open", "high", "low", "close", "settlement", "volume"]
]
print(ru.to_string())
