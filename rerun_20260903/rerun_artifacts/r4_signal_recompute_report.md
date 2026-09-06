# R4 — Independent Recompute of the v4_2 Signal-Generation Layer

**Verifier:** read-only independent recomputation (pandas/numpy only; no framework
`signals*`/`analytics*` import for computation). Frozen normalized data reused; no
Panama/mapping recompute.

**Artifacts produced:**
- `r4_signal_recompute.py` (this recompute + comparison driver)
- `r4_recompute_comparison.json` (machine-readable comparison result)
- `r4_recomputed_S1_targets.pkl` (recomputed S1 targets table)
- `r4_recomputed_S1_internal_targets.pkl` (S1 per-horizon/sector internal sizing rows)

---

## 1. What was recomputed

Pipeline under test (identical to framework source, reimplemented line-by-line):

1. **Score layer** — `price_diff_sharpe` for horizons `single_20_skip5` (window 20,
   skip 5) and `single_250` (window 250, skip 0): `usable = changes.shift(skip)`,
   rolling mean / rolling `std(ddof=1)` over `window` with `min_periods=window`,
   divided, `* sqrt(252)`. S1 sleeve score = mean of the two horizon score frames.
2. **Daily vol** — `robust_price_volatility`: `ewm(span=35, min_periods=10,
   adjust=True).std(bias=False)`, `.clip(lower=1e-10)`, floor =
   `rolling(500, min_periods=100).quantile(0.05)`, then `combine(floor, np.maximum)`.
3. **Eligibility / liquidity** — mapping→bars merge, pivot volume/OI, reindex to
   price dates, `rolling(20, min_periods=10).median()`; eligible =
   `median_volume>=10000 & median_oi>=20000`.
4. **Weekly selection** — `weekly_select_v42` over the calendar
   `weekly_signal_dates` (W-FRI end-of-open-week rule), cross-sectional
   strongest/weakest vs absolute sign-of-score, with direction rows emitted for
   every score date carrying the current signal date.
5. **Combined sleeve signal** — directions = sign of sum of horizon directions;
   selections = concat with `horizon` column.
6. **Full engine loop** (required to reproduce `targets.pkl`, because
   `optimal_position`/`buffered_target` depend on running equity) —
   `BacktestEngineV3.run` reimplemented: pending orders filled at next open with
   lagged liquidity, FIFO lot ledger + `FeeSchedule.charge` (client = 1.5×exchange),
   mark-to-market (settlement>0 else close), equity update, then
   `SleeveEngineV42._calculate_targets` (equal-risk 0.5/0.5 per-horizon budget,
   netting, `_cap_final_liquidity`, `_scale_to_exante_volatility` via `np.cov(ddof=1)`,
   `_scale_by_realized_volatility`), then `_scheduled_targets` (10% buffer,
   hybrid weekly rebalance, hard margin/leverage caps), then order generation.
   S1 uses the sleeve engine; G1/G2 use the single-horizon `BacktestEngineV42`.

## 2. Match statistics

Comparison is an outer merge on the natural key of each table, with per-row
agreement on every compared column.

### S1 — `S1__strategy_sleeve_20skip5_250_equal_risk`

| Table | Rows (recorded / recomputed / joined) | Result |
|---|---|---|
| `scores.pkl` | 52343 / 52343 / 52343 | **max abs diff = 0.0** (bit-exact) |
| — sign agreement (non-zero, comparable) | 45334 / 45334 | **100.0%** |
| — NaN cells (warmup) | 6995 / 6995 | **all aligned** |
| `selections.pkl` | 8112 / 8112 / 8112 | direction 8112/8112, score 8112/8112, max score diff 0.0 |
| `targets.pkl` | 21402 / 21402 / 21402 | optimal 21402/21402, buffered 21402/21402, nrd 21402/21402, emergency 21402/21402 |

### G1 — `G1__single_20_skip5`

| Table | Rows | Result |
|---|---|---|
| `scores.pkl` | 52343 | max abs diff 0.0, sign 100.0% (45222 comparable), NaN cells 6995/6995 aligned |
| `selections.pkl` | 4188 | direction 4188/4188, score 4188/4188, max score diff 0.0 |
| `targets.pkl` | 18502 | optimal 18502/18502, buffered 18502/18502, nrd + emergency 18502/18502 |

### G2 — `G2__single_250`

| Table | Rows | Result |
|---|---|---|
| `scores.pkl` | 52343 | max abs diff 0.0, sign 100.0% (41494 comparable), NaN cells 10820/10820 aligned |
| `selections.pkl` | 3924 | direction 3924/3924, score 3924/3924, max score diff 0.0 |
| `targets.pkl` | 18638 | optimal 18638/18638, buffered 18638/18638, nrd + emergency 18638/18638 |

In every table the "only recorded" and "only recomputed" counts are **0**: row keys
(date/instrument, signal-date/sector/instrument/role, date/contract) are identical.

## 3. Discrepancies

**None found at any layer for any scenario.**

- Scores: `max_abs_diff == 0.0` (every overlapping finite cell is bit-identical).
  The remaining cells are NaN in both files in exactly the same positions (6995 for
  the 20-skip5 and sleeve horizons, 10820 for the 250 horizon — exactly the lookback
  warm-up region), i.e. `nan_cells_matching == nan_cells_total`.
- Selections: direction and score columns agree on 100% of rows; row sets equal.
- Targets: `optimal_position` and `buffered_target` (integer lots) agree on 100% of
  rows, as do `normal_rebalance_day` and `emergency_trigger`. The disagreement list
  is empty, so line-level attribution is trivially empty.

## 4. Conclusion

The v4_2 signal-generation layer (score → weekly selection → eligibility → target
pipeline, including the full equity/PNL/fee/order path required to recover
`optimal_position` and `buffered_target`) is reproduced **exactly** from the frozen
normalized data using only pandas/numpy. All three scenarios (S1 sleeve, G1, G2)
verify bit-identically against the recorded `scores.pkl`, `selections.pkl`, and
`targets.pkl`.
