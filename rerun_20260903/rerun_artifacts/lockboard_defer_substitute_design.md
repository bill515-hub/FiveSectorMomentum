# Locked-limit order handling: defer + substitute (design note)

Status: confirmed by user directive (2026 turn).

## User rule (confirmed)

1. **Limit-up (涨停) buy blocked at open** — the engine may not trade a limit-up
   board at the open print:
   - **Absolute sectors** (`ferrous` RB, `government_bond` T, `base_metal` AL):
     defer the same order to the **next trading day**.
   - **Cross-sectional sectors** (`agriculture`, `chemical_energy`): substitute
     with the **next-ranked** instrument in the same sector (`排名靠后的一个品种`).
2. **Limit-down (跌停) sell blocked at open** — two treatments, run and compared:
   - **Variant A "symmetric defer"**: defer the sell to the next trading day.
   - **Variant B "reject"**: reject outright (current behaviour, no defer/substitute).

## Implementation plan (copy `rerun_20260903/` only; original repo untouched)

### 1. Correct limit-price derivation (M3 rework)
The earlier `high==low & vol>0` heuristic over **all** contracts produced 16902
"locked" days — wrong. Audit ground truth is 12 lock days on **main-mapped**
contracts plus the RU2505 2025-04-07 **roll old-leg** limit-down sell.

Fix: restrict lock detection to bars the engine actually trades (main-mapped
contract per `(date, instrument)`, plus roll old-leg contracts on roll days).
On a locked day set the binding side:
- limit-up lock → `upper_limit = settlement` (buy is adverse when open ≥ upper_limit)
- limit-down lock → `lower_limit = settlement` (sell is adverse when open ≤ lower_limit)

Non-locked bars keep `upper_limit`/`lower_limit` = NaN (no clamp, no reject).

### 2. Engine changes (`engine_v3.py`, copy)
- Add a `deferred` order queue that persists **across days regardless of
  `unfilled_mode`** (today `cancel_recalculate` clears `pending` each day).
- In `_execute_order_v3`, replace the hard `adverse_limit_at_open` rejection with:
  - BUY + absolute sector → defer (requeue next day).
  - BUY + cross-sectional sector → substitute: pick the runner-up (2nd-highest
    eligible score at the signal date), re-size, and order it instead.
  - SELL → variant A defer / variant B reject (scenario flag).

### 3. Sell-side variants
Two scenario runs, identical buy-side handling, differing sell-side treatment:
- `lockboard_symmetric_defer`
- `lockboard_reject_sell`

## Open implementation decisions (to settle before coding)
- Substitute re-sizing: runner-up gets its own score/vol-based target (not the
  blocked instrument's lot count).
- Defer retry cap: defer once (next day) then reject if still locked, vs defer
  until fillable.
- Whether the runner-up substitution also applies to the short side (limit-down
  buy-back of a short = limit-up buy, covered above; short-side limit-down is a
  *sell* so falls under sell variants).
