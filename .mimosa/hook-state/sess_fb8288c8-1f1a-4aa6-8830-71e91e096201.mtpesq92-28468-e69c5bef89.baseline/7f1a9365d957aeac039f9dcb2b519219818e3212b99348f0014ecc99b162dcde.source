import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(r"D:\FiveSectorMomentum")
cal = pd.read_pickle(ROOT/"outputs"/"v4_2_20260903_091241"/"calendar"/"calendar_daily.pkl")
print("calendar_daily", cal.shape, list(cal.columns))
print(cal.head(3).to_string())
print(cal.tail(2).to_string())
print("is_open values:", sorted(cal.is_open.unique()))
print("date range:", cal.date.min(), cal.date.max(), len(cal))

fr = pd.read_pickle(ROOT/"data"/"v3"/"fees"/"historical_fee_rules.pkl")
print("="*50)
print("fee_rules", fr.shape, list(fr.columns))
print(fr.head(4).to_string())
print(fr[fr.contract.ne('*')].contract.nunique(), "exact contracts;", fr[fr.contract.eq('*')].shape[0], "wildcard rows")
print("trade_type:", sorted(fr.trade_type.unique()))
print("effective range:", fr.effective_from.min(), fr.effective_to.max())
# a sample lookup key for a universe contract
print(fr[fr.contract.eq('RB1501.SHF')].to_string())
