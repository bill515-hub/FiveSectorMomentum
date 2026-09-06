"""R4: independent recomputation of the v4_2 signal-generation layer.

Pipeline under verification (S1 sleeve = single_20_skip5 + single_250):
    score (price-diff Sharpe) -> weekly calendar selection -> eligibility ->
    equal-risk internal targets -> netting -> liquidity cap -> ex-ante covariance
    scaling -> realized-vol feedback -> buffer -> hard margin/leverage constraints.

This script does NOT import any `signals*` / `analytics*` module for computation.
It reuses the frozen normalized data and reimplements the engine loop from the
framework source using only pandas + numpy + math.

Outputs (new files only, under rerun_artifacts/):
    - recomputed comparison JSON + markdown report written by the caller.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
DATA = ROOT / "data" / "normalized_v2"
OUT = ROOT / "outputs" / "v4_2_20260903_091241"
CAL_PKL = OUT / "calendar" / "calendar_daily.pkl"
FEE_RULES_PKL = ROOT / "data" / "v3" / "fees" / "historical_fee_rules.pkl"
ART = ROOT / "rerun_20260903" / "rerun_artifacts"
ART.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# Frozen constants (mirroring configs/five_sector_momentum_v4_2_repaired.yaml)
# ----------------------------------------------------------------------------
RUN_START = pd.Timestamp("2015-01-01")
RUN_END = pd.Timestamp("2026-08-31")
INITIAL_CAPITAL = 10000000.0
ANNUALIZATION = 252.0
VOL_CONFIG = dict(ewma_span_days=35, min_periods=10, floor_enabled=True,
                  floor_quantile=0.05, floor_lookback_days=500,
                  floor_min_periods=100, absolute_min=1e-10)
ELIG_CONFIG = dict(liquidity_lookback_days=20, liquidity_min_periods=10,
                   min_median_volume=10000, min_median_open_interest=20000)
SIGNAL_CONFIG = dict(annualization_days=252.0, min_eligible_instruments=2,
                     long_threshold=0.0, short_threshold=0.0)
SECTOR_WEIGHTS = {"ferrous": 0.20, "agriculture": 0.20,
                  "chemical_energy": 0.20, "government_bond": 0.20,
                  "base_metal": 0.20}
COV_SCALING = dict(enabled=True, lookback_days=252, min_periods=126,
                   minimum_multiplier=0.50, maximum_multiplier=3.00)
REALIZED_FEEDBACK = dict(enabled=True, ewma_span_days=63, min_periods=63,
                         minimum_multiplier=0.75, maximum_multiplier=1.35)
ANNUAL_VOL_TARGET = 0.275
BUFFER_FRACTION = 0.10
BROKER_MARGIN_MULT = 1.25
MAX_COMMODITY_MARGIN = 0.65
MAX_TOTAL_MARGIN = 0.78
MAX_COMMODITY_LEVERAGE = 8.0
EXEMPT_SECTORS = {"government_bond"}
VOL_FRACTION = 0.05
OI_FRACTION = 0.01
MAX_PARTICIPATION = 0.05
FALLBACK_VOLUME = 10000
HIGH_LIQ = {"T", "RB", "AL"}
HIGH_MIN_VOL = 10000.0
HIGH_MIN_OI = 20000.0
ROLL_EXTRA_TICKS = 1.0
FEE_MULTIPLIER = 1.5
EMERGENCY_VOL_RATIO = 1.20

# FALLBACK_ECONOMICS for the 17 instruments (mirrors src/universe.py).
FALLBACK_ECONOMICS = {
    "RB": (10.0, 1.0, 0.13), "T": (10000.0, 0.005, 0.03), "AL": (5.0, 5.0, 0.13),
    "C": (10.0, 1.0, 0.12), "M": (10.0, 1.0, 0.12), "P": (10.0, 2.0, 0.13),
    "JD": (10.0, 1.0, 0.15), "LH": (16.0, 5.0, 0.18), "CF": (5.0, 5.0, 0.12),
    "SR": (10.0, 1.0, 0.12), "AP": (10.0, 1.0, 0.15), "FG": (20.0, 1.0, 0.15),
    "MA": (10.0, 1.0, 0.15), "UR": (20.0, 1.0, 0.15), "RU": (10.0, 5.0, 0.15),
    "SP": (10.0, 2.0, 0.13), "SC": (1000.0, 0.1, 0.18),
}


def fallback(instrument: str):
    return FALLBACK_ECONOMICS.get(instrument, (1.0, 1.0, 0.18))


# ----------------------------------------------------------------------------
# Data loading (frozen files)
# ----------------------------------------------------------------------------
def load():
    bars = pd.read_pickle(DATA / "bars.pkl")
    mapping = pd.read_pickle(DATA / "mapping.pkl")
    adjusted = pd.read_pickle(DATA / "adjusted_prices.pkl")
    contract_meta = pd.read_pickle(DATA / "contract_meta.pkl")
    instrument_meta = pd.read_pickle(DATA / "instrument_meta.pkl")
    calendar_daily = pd.read_pickle(CAL_PKL)
    fee_rules = pd.read_pickle(FEE_RULES_PKL)
    return bars, mapping, adjusted, contract_meta, instrument_meta, calendar_daily, fee_rules


# ----------------------------------------------------------------------------
# Calendar (mirrors TradingCalendarV42)
# ----------------------------------------------------------------------------
class Calendar:
    def __init__(self, daily: pd.DataFrame):
        frame = daily.copy()
        frame["date"] = pd.to_datetime(frame.date)
        wide = frame.pivot(index="date", columns="exchange", values="is_open").sort_index()
        if not wide.stack().isin([0, 1]).all():
            raise ValueError("unknown open flag")
        if wide.max(axis=1).ne(wide.min(axis=1)).any():
            raise ValueError("exchange calendars disagree")
        self.daily = pd.DataFrame({"date": wide.index, "is_open": wide.max(axis=1).astype(int).values})
        self.open_flags = self.daily.set_index("date").is_open

    def weekly_signal_dates(self, observed):
        dates = pd.DatetimeIndex(observed)
        if dates.has_duplicates or not dates.is_monotonic_increasing:
            raise ValueError("dates must be unique and sorted")
        out = []
        for date in dates:
            friday = date.to_period("W-FRI").end_time.normalize()
            rest = pd.date_range(date, friday)
            if not rest.isin(self.open_flags.index).all():
                raise ValueError(f"incomplete week at {date.date()}")
            if self.open_flags.loc[date] != 1:
                raise ValueError(f"price on non-session {date.date()}")
            if self.open_flags.reindex(rest[1:]).sum() == 0:
                out.append(date)
        return pd.DatetimeIndex(out)


# ----------------------------------------------------------------------------
# Signal layer
# ----------------------------------------------------------------------------
def price_diff_sharpe(changes: pd.DataFrame, window: int, skip: int) -> pd.DataFrame:
    usable = changes.shift(skip)
    mean = usable.rolling(window, min_periods=window).mean()
    std = usable.rolling(window, min_periods=window).std(ddof=1)
    return mean.divide(std.replace(0.0, np.nan)) * np.sqrt(ANNUALIZATION)


def robust_price_volatility(changes: pd.DataFrame) -> pd.DataFrame:
    vol = changes.ewm(span=VOL_CONFIG["ewma_span_days"],
                      min_periods=VOL_CONFIG["min_periods"], adjust=True).std(bias=False)
    vol = vol.clip(lower=VOL_CONFIG["absolute_min"])
    if VOL_CONFIG["floor_enabled"]:
        floor = vol.rolling(VOL_CONFIG["floor_lookback_days"],
                            min_periods=VOL_CONFIG["floor_min_periods"]).quantile(
                                VOL_CONFIG["floor_quantile"])
        vol = vol.combine(floor, np.maximum)
    return vol


def build_liquidity(mapping: pd.DataFrame, bars: pd.DataFrame, dates) -> tuple:
    mapped = mapping.merge(
        bars[["date", "ts_code", "volume", "oi"]],
        left_on=["date", "contract"], right_on=["date", "ts_code"], how="left",
    )
    volume = mapped.pivot(index="date", columns="instrument", values="volume").reindex(dates)
    oi = mapped.pivot(index="date", columns="instrument", values="oi").reindex(dates)
    mv = volume.rolling(ELIG_CONFIG["liquidity_lookback_days"],
                        min_periods=ELIG_CONFIG["liquidity_min_periods"]).median()
    moi = oi.rolling(ELIG_CONFIG["liquidity_lookback_days"],
                     min_periods=ELIG_CONFIG["liquidity_min_periods"]).median()
    elig = mv.ge(ELIG_CONFIG["min_median_volume"]) & moi.ge(ELIG_CONFIG["min_median_open_interest"])
    return elig, mv, moi


def wide_to_long(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    return (frame.rename_axis(index="date", columns="instrument")
                 .stack(future_stack=True).rename(value_name).reset_index())


def selection_row(date, sector, instrument, direction, score, role):
    return {"signal_date": date, "sector": sector, "instrument": instrument,
            "direction": direction, "score": float(score), "role": role}


def weekly_select_v42(scores: pd.DataFrame, eligibility: pd.DataFrame,
                      instrument_meta: pd.DataFrame, calendar: Calendar):
    signal_dates = calendar.weekly_signal_dates(scores.index)
    meta = instrument_meta.set_index("instrument")
    instruments = list(meta.index)
    current = pd.Series(0, index=instruments, dtype=int)
    current_signal_date = pd.NaT
    direction_rows = []
    selection_rows = []
    signal_date_set = set(pd.DatetimeIndex(signal_dates.values))
    for date in scores.index:
        if date in signal_date_set:
            current[:] = 0
            current_signal_date = date
            date_scores = scores.loc[date].where(
                eligibility.loc[date].reindex(scores.columns).fillna(False))
            for sector, sector_meta in meta.groupby("sector"):
                members = list(sector_meta.index)
                eligible = date_scores.reindex(members).dropna()
                mode = sector_meta["mode"].iloc[0]
                if mode == "cross_sectional":
                    if len(eligible) < int(SIGNAL_CONFIG["min_eligible_instruments"]):
                        continue
                    strongest = eligible.idxmax()
                    weakest = eligible.idxmin()
                    if eligible[strongest] > float(SIGNAL_CONFIG["long_threshold"]):
                        current[strongest] = 1
                        selection_rows.append(selection_row(
                            date, sector, strongest, 1, eligible[strongest], "strongest"))
                    if weakest != strongest and eligible[weakest] < float(SIGNAL_CONFIG["short_threshold"]):
                        current[weakest] = -1
                        selection_rows.append(selection_row(
                            date, sector, weakest, -1, eligible[weakest], "weakest"))
                else:
                    for instrument, score in eligible.items():
                        direction = (int(score > float(SIGNAL_CONFIG["long_threshold"]))
                                     - int(score < float(SIGNAL_CONFIG["short_threshold"])))
                        current[instrument] = direction
                        if direction:
                            selection_rows.append(selection_row(
                                date, sector, instrument, direction, score, "absolute"))
        for instrument, direction in current.items():
            direction_rows.append({
                "date": date, "signal_date": current_signal_date,
                "instrument": instrument,
                "sector": meta.loc[instrument, "sector"],
                "direction": int(direction)})
    return pd.DataFrame(selection_rows), pd.DataFrame(direction_rows)


def build_bundle(forecast: pd.DataFrame, label: str, library, instrument_meta, calendar):
    scores = forecast.reindex(index=library["prices"].index, columns=library["prices"].columns)
    selections, directions = weekly_select_v42(
        scores, library["eligibility"], instrument_meta, calendar)
    liquidity = (wide_to_long(library["median_volume"], "median_volume")
                 .merge(wide_to_long(library["median_oi"], "median_open_interest"),
                        on=["date", "instrument"], how="outer"))
    return {
        "scores": wide_to_long(scores, "score"),
        "daily_price_vol": wide_to_long(library["daily_vol"], "daily_price_vol"),
        "eligibility": wide_to_long(library["eligibility"], "eligible"),
        "liquidity": liquidity,
        "selections": selections,
        "directions": directions,
    }


def combined_sleeve_signal(bundles: dict):
    first = bundles[sorted(bundles)[0]]
    direction_frames, score_frames, selections = [], [], []
    for horizon, b in sorted(bundles.items()):
        direction_frames.append(
            b["directions"].set_index(["date", "instrument"])["direction"].rename(horizon))
        score_frames.append(
            b["scores"].set_index(["date", "instrument"])["score"].rename(horizon))
        selections.append(b["selections"].assign(horizon=horizon))
    directions = (pd.concat(direction_frames, axis=1).sum(axis=1)
                  .apply(np.sign).astype(int).rename("direction").reset_index())
    meta = first["directions"][["instrument", "sector"]].drop_duplicates()
    directions = directions.merge(meta, on="instrument", how="left")
    signal_dates = first["directions"][["date", "signal_date"]].drop_duplicates("date")
    directions = directions.merge(signal_dates, on="date", how="left")[
        ["date", "signal_date", "instrument", "sector", "direction"]]
    scores = pd.concat(score_frames, axis=1).mean(axis=1).rename("score").reset_index()
    return {
        "scores": scores,
        "daily_price_vol": first["daily_price_vol"],
        "eligibility": first["eligibility"],
        "liquidity": first["liquidity"],
        "selections": pd.concat(selections, ignore_index=True),
        "directions": directions,
    }


# ----------------------------------------------------------------------------
# Fee schedule (mirrors costs_v3.FeeSchedule)
# ----------------------------------------------------------------------------
class FeeSchedule:
    def __init__(self, rules: pd.DataFrame):
        self.rules = rules.copy()
        self.rules["effective_from"] = pd.to_datetime(self.rules["effective_from"])
        self.rules["effective_to"] = pd.to_datetime(self.rules["effective_to"])
        self._groups = {key: g.sort_values("effective_from")
                        for key, g in self.rules.groupby(
                            ["contract", "instrument", "trade_type"])}

    def charge(self, contract, instrument, date, trade_type, lots, price,
               point_value, client_multiplier):
        row = self._lookup(contract, instrument, pd.Timestamp(date), trade_type)
        exchange = abs(lots) * (float(row["fee_per_lot"])
                                + price * point_value * float(row["fee_rate"]))
        return {"exchange_fee": exchange, "client_fee": exchange * client_multiplier,
                "fee_per_lot": float(row["fee_per_lot"]), "fee_rate": float(row["fee_rate"]),
                "rule_id": str(row["rule_id"]), "source_type": str(row["source_type"]),
                "source_url": str(row["source_url"]), "is_proxy": bool(row["is_proxy"])}

    def _lookup(self, contract, instrument, date, trade_type):
        for key in [(contract, instrument, trade_type), ("*", instrument, trade_type)]:
            group = self._groups.get(key)
            if group is None:
                continue
            matched = group[group["effective_from"].le(date) & group["effective_to"].ge(date)]
            if not matched.empty:
                return matched.iloc[-1]
        raise KeyError(f"no fee rule {contract} {instrument} {date.date()} {trade_type}")


# ----------------------------------------------------------------------------
# Engine reimplementation (mirrors BacktestEngine / V3 / V41 / V42 / Sleeve)
# ----------------------------------------------------------------------------
@dataclass
class PendingOrder:
    contract: str
    instrument: str
    quantity: int
    created_date: pd.Timestamp
    reason: str
    attempts: int = 0


def buffered_position(current, optimal, fraction):
    if optimal == 0:
        return 0
    if fraction <= 0:
        return int(optimal)
    width = max(1.0, abs(optimal) * fraction)
    lower, upper = optimal - width, optimal + width
    if lower <= current <= upper:
        return int(current)
    if current < lower:
        return int(math.ceil(lower))
    return int(math.floor(upper))


def apply_trade_to_lot_ledger(lots, quantity, date):
    if quantity == 0:
        return []
    date = pd.Timestamp(date)
    net = int(sum(int(i["quantity"]) for i in lots))
    if net == 0 or np.sign(net) == np.sign(quantity):
        lots.append({"open_date": date, "quantity": int(quantity)})
        return [(int(quantity), "open")]
    remaining = abs(int(quantity))
    order_sign = int(np.sign(quantity))
    segments = []
    lots.sort(key=lambda item: pd.Timestamp(item["open_date"]))
    for lot in list(lots):
        if remaining == 0:
            break
        if int(lot["quantity"]) == 0 or np.sign(lot["quantity"]) == order_sign:
            continue
        close_abs = min(remaining, abs(int(lot["quantity"])))
        segment_quantity = order_sign * close_abs
        trade_type = ("close_today"
                      if pd.Timestamp(lot["open_date"]).normalize() == date.normalize()
                      else "close_non_today")
        segments.append((segment_quantity, trade_type))
        lot["quantity"] = int(lot["quantity"]) + segment_quantity
        remaining -= close_abs
    lots[:] = [i for i in lots if int(i["quantity"]) != 0]
    if remaining:
        open_quantity = order_sign * remaining
        lots.append({"open_date": date, "quantity": open_quantity})
        segments.append((open_quantity, "open"))
    return segments


class Engine:
    def __init__(self, data, signals, fee_schedule, directions_by_horizon=None):
        self.bars = data["bars"].set_index(["date", "ts_code"]).sort_index()
        self.mapping = data["mapping"].set_index(["date", "instrument"])["contract"].to_dict()
        self.directions = signals["directions"].set_index(["date", "instrument"])["direction"].to_dict()
        self.price_vol = signals["daily_price_vol"].set_index(["date", "instrument"])["daily_price_vol"].to_dict()
        self.liquidity = signals["liquidity"].set_index(["date", "instrument"])[
            ["median_volume", "median_open_interest"]].to_dict("index")
        self.instrument_meta = data["instrument_meta"].set_index("instrument")
        self.sector_by_instrument = self.instrument_meta["sector"].to_dict()
        self.contract_meta = data["contract_meta"].set_index("ts_code")
        self.price_changes = (data["adjusted_prices"]
                              .pivot(index="date", columns="instrument", values="adjusted_price")
                              .sort_index().diff())
        self.fee_schedule = fee_schedule
        self.directions_by_horizon = directions_by_horizon
        self.internal_target_rows = []
        self.net_target_rows = []
        self.risk_rows = []

    # ---- helpers -----------------------------------------------------------
    def _instrument_for_contract(self, contract):
        if contract in self.contract_meta.index:
            value = self.contract_meta.loc[contract, "instrument"]
            return str(value.iloc[-1] if isinstance(value, pd.Series) else value)
        letters = "".join(c for c in contract.split(".")[0] if c.isalpha())
        return letters.upper()

    def _contract_value(self, contract, column, fb):
        if contract in self.contract_meta.index and column in self.contract_meta:
            value = self.contract_meta.loc[contract, column]
            if isinstance(value, pd.Series):
                value = value.iloc[-1]
            if pd.notna(value):
                return float(value)
        return fb

    @staticmethod
    def _value(row, key, fb):
        value = row.get(key, np.nan)
        return float(value) if pd.notna(value) else float(fb)

    @staticmethod
    def _mark_price(bar):
        settlement = bar.get("settlement", np.nan)
        if pd.notna(settlement) and float(settlement) > 0:
            return float(settlement)
        return float(bar["close"])

    def _get_bar(self, key):
        if key not in self.bars.index:
            return None
        bar = self.bars.loc[key]
        if isinstance(bar, pd.DataFrame):
            bar = bar.iloc[-1]
        return bar

    # ---- sizing ------------------------------------------------------------
    @staticmethod
    def _scale_integer_targets(targets, scale):
        for contract, quantity in list(targets.items()):
            targets[contract] = int(math.copysign(math.floor(abs(quantity) * scale), quantity))
            if targets[contract] == 0:
                targets.pop(contract)

    @staticmethod
    def _scale_subset_targets(targets, contracts, scale):
        for contract in contracts:
            if contract not in targets:
                continue
            quantity = targets[contract]
            targets[contract] = int(math.copysign(math.floor(abs(quantity) * scale), quantity))
            if targets[contract] == 0:
                targets.pop(contract)

    def _split_exempt(self, positions):
        commodity, exempt = {}, {}
        for contract, quantity in positions.items():
            instrument = self._instrument_for_contract(contract)
            sector = self.sector_by_instrument.get(instrument)
            (exempt if sector in EXEMPT_SECTORS else commodity)[contract] = quantity
        return commodity, exempt

    def _margin_required(self, date, positions):
        total = 0.0
        for contract, quantity in positions.items():
            bar = self._get_bar((date, contract))
            if bar is None:
                continue
            instrument = self._instrument_for_contract(contract)
            pv = self._value(bar, "point_value", fallback(instrument)[0])
            reported = max(self._value(bar, "long_margin_rate", 0.0),
                           self._value(bar, "short_margin_rate", 0.0))
            base = max(reported, fallback(instrument)[2])
            total += abs(quantity) * self._mark_price(bar) * pv * base * BROKER_MARGIN_MULT
        return total

    def _gross_notional(self, date, positions):
        total = 0.0
        for contract, quantity in positions.items():
            bar = self._get_bar((date, contract))
            if bar is None:
                continue
            pv = self._value(bar, "point_value", fallback(self._instrument_for_contract(contract))[0])
            total += abs(quantity) * self._mark_price(bar) * pv
        return total

    def _scale_for_portfolio_constraints(self, date, targets, equity):
        commodity, _ = self._split_exempt(targets)
        cm = self._margin_required(date, commodity)
        cm_limit = equity * MAX_COMMODITY_MARGIN
        if cm > cm_limit and cm > 0:
            self._scale_subset_targets(targets, set(commodity), cm_limit / cm)
        commodity, _ = self._split_exempt(targets)
        cg = self._gross_notional(date, commodity)
        cg_limit = equity * MAX_COMMODITY_LEVERAGE
        if cg > cg_limit and cg > 0:
            self._scale_subset_targets(targets, set(commodity), cg_limit / cg)
        total_margin = self._margin_required(date, targets)
        tm_limit = equity * MAX_TOTAL_MARGIN
        if total_margin > tm_limit and total_margin > 0:
            commodity, exempt = self._split_exempt(targets)
            commodity_margin = self._margin_required(date, commodity)
            exempt_margin = self._margin_required(date, exempt)
            available = max(0.0, tm_limit - commodity_margin)
            if exempt_margin > 0:
                self._scale_subset_targets(targets, set(exempt), available / exempt_margin)
            else:
                self._scale_integer_targets(targets, tm_limit / total_margin)

    def _scale_to_exante(self, date, targets, equity, target_vol):
        cfg = COV_SCALING
        if not cfg["enabled"] or len(targets) < 2:
            return float("nan"), 1.0
        contracts = list(targets)
        instruments = [self._instrument_for_contract(c) for c in contracts]
        window = self.price_changes.loc[:date, instruments].tail(cfg["lookback_days"]).dropna()
        if len(window) < cfg["min_periods"]:
            return float("nan"), 1.0
        point_values = np.array([
            self._contract_value(c, "point_value", fallback(i)[0])
            for c, i in zip(contracts, instruments)])
        quantities = np.array([targets[c] for c in contracts], dtype=float)
        monetary = window.to_numpy(dtype=float) * point_values
        cov = np.cov(monetary, rowvar=False, ddof=1)
        if np.ndim(cov) != 2 or not np.isfinite(cov).all():
            return float("nan"), 1.0
        daily_var = float(quantities @ cov @ quantities)
        if daily_var <= 0:
            return float("nan"), 1.0
        exante = math.sqrt(daily_var * ANNUALIZATION) / equity
        mult = float(np.clip(target_vol / exante, cfg["minimum_multiplier"],
                             cfg["maximum_multiplier"]))
        self._scale_integer_targets(targets, mult)
        return exante, mult

    def _scale_by_realized(self, targets, returns, target_vol):
        cfg = REALIZED_FEEDBACK
        minimum = cfg["min_periods"]
        if not cfg["enabled"] or len(returns) < minimum:
            return float("nan"), 1.0
        series = pd.Series(returns, dtype=float)
        trailing = float(series.ewm(span=cfg["ewma_span_days"], min_periods=minimum,
                                    adjust=False).std(bias=False).iloc[-1]
                         * math.sqrt(ANNUALIZATION))
        if not np.isfinite(trailing) or trailing <= 0:
            return float("nan"), 1.0
        mult = float(np.clip(target_vol / trailing, cfg["minimum_multiplier"],
                             cfg["maximum_multiplier"]))
        self._scale_integer_targets(targets, mult)
        return trailing, mult

    def _cap_final_liquidity(self, date, targets):
        for contract in list(targets):
            instrument = self._instrument_for_contract(contract)
            liq = self.liquidity.get((date, instrument), {})
            caps = []
            if np.isfinite(liq.get("median_volume", np.nan)):
                caps.append(int(math.floor(liq["median_volume"] * VOL_FRACTION)))
            if np.isfinite(liq.get("median_open_interest", np.nan)):
                caps.append(int(math.floor(liq["median_open_interest"] * OI_FRACTION)))
            if caps:
                targets[contract] = int(np.sign(targets[contract]) * min(abs(targets[contract]), min(caps)))
            if not targets[contract]:
                targets.pop(contract)

    # ---- execution ---------------------------------------------------------
    @staticmethod
    def _impact_ticks(participation):
        if participation <= 0.01:
            return 0.0
        if participation <= 0.03:
            return 1.0
        return 2.0

    @staticmethod
    def _adverse_grid_price(price, tick, quantity):
        units = price / tick
        snapped = math.ceil(units - 1e-10) if quantity > 0 else math.floor(units + 1e-10)
        return float(round(snapped * tick, 10))

    def _base_slippage_ticks(self, instrument, liquidity):
        high = (instrument in HIGH_LIQ
                and float(liquidity.get("median_volume", 0.0)) >= HIGH_MIN_VOL
                and float(liquidity.get("median_open_interest", 0.0)) >= HIGH_MIN_OI)
        base = 1 if high else 2
        return float(max(0, base)), ("high" if base == 1 else "other")

    def _execute_order_v3(self, date, order, lots, fee_mult):
        key = (date, order.contract)
        bar = self._get_bar(key)
        if bar is None:
            return [], order.quantity, {"reason": "missing_bar", "quantity_remaining": order.quantity,
                                        "date": date, "created_date": order.created_date,
                                        "contract": order.contract, "instrument": order.instrument,
                                        "attempt": order.attempts}
        if not np.isfinite(bar.get("open", np.nan)):
            return [], order.quantity, {"reason": "no_open", "quantity_remaining": order.quantity,
                                        "date": date, "created_date": order.created_date,
                                        "contract": order.contract, "instrument": order.instrument,
                                        "attempt": order.attempts}
        # bars carry no upper/lower limit columns in this dataset -> no locked-limit checks fire.
        liquidity = self.liquidity.get((order.created_date, order.instrument), {})
        available = float(liquidity.get("median_volume", np.nan))
        if not np.isfinite(available) or available <= 0:
            available = FALLBACK_VOLUME
        maximum = max(0, int(math.floor(available * MAX_PARTICIPATION)))
        fill_abs = min(abs(order.quantity), maximum)
        if fill_abs == 0:
            return [], order.quantity, {"reason": "lagged_participation_limit",
                                        "quantity_remaining": order.quantity, "date": date,
                                        "created_date": order.created_date,
                                        "contract": order.contract, "instrument": order.instrument,
                                        "attempt": order.attempts}
        total_fill = int(math.copysign(fill_abs, order.quantity))
        participation = fill_abs / available
        impact = self._impact_ticks(participation)
        base, _ = self._base_slippage_ticks(order.instrument, liquidity)
        roll = ROLL_EXTRA_TICKS if order.reason == "roll" else 0.0
        total_ticks = base + roll + impact
        tick = self._value(bar, "tick_size", fallback(order.instrument)[1])
        raw_price = float(bar["open"]) + math.copysign(total_ticks * tick, total_fill)
        fill_price = self._adverse_grid_price(raw_price, tick, total_fill)
        pv = self._value(bar, "point_value", fallback(order.instrument)[0])
        segments = apply_trade_to_lot_ledger(lots.setdefault(order.contract, []),
                                             total_fill, pd.Timestamp(date))
        fills = []
        for seg_index, (seg_qty, trade_type) in enumerate(segments, start=1):
            charge = self.fee_schedule.charge(order.contract, order.instrument, date,
                                              trade_type, abs(seg_qty), fill_price, pv,
                                              fee_mult)
            fills.append({
                "date": date, "created_date": order.created_date, "contract": order.contract,
                "instrument": order.instrument, "quantity": seg_qty,
                "segment_index": seg_index, "transaction_type": trade_type,
                "price": fill_price, "open_price": float(bar["open"]),
                "point_value": pv, "commission": charge["client_fee"],
                "exchange_commission": charge["exchange_fee"],
                "fee_per_lot": charge["fee_per_lot"], "fee_rate": charge["fee_rate"],
                "fee_rule_id": charge["rule_id"], "fee_source_type": charge["source_type"],
                "fee_is_proxy": charge["is_proxy"], "base_slippage_ticks": base,
                "roll_extra_ticks": roll, "impact_ticks": impact,
                "total_slippage_ticks": total_ticks, "participation_rate": participation,
                "lagged_median_volume": available, "attempt": order.attempts,
                "reason": order.reason,
            })
        remainder = order.quantity - total_fill
        rejection = None
        if remainder:
            rejection = {"reason": "partial_fill", "quantity_remaining": remainder, "date": date,
                         "created_date": order.created_date, "contract": order.contract,
                         "instrument": order.instrument, "attempt": order.attempts}
        return fills, remainder, rejection

    def _mark_to_market(self, date, start_positions, fills, previous_marks):
        pnl = 0.0
        stale = 0
        contracts = set(start_positions) | {f["contract"] for f in fills}
        for contract in contracts:
            bar = self._get_bar((date, contract))
            if bar is None:
                stale += 1
                continue
            mark = self._mark_price(bar)
            instrument = self._instrument_for_contract(contract)
            pv = self._value(bar, "point_value", fallback(instrument)[0])
            old_position = start_positions.get(contract, 0)
            previous = previous_marks.get(contract)
            contract_pnl = 0.0
            contract_fills = [f for f in fills if f["contract"] == contract]
            if old_position and previous is not None and np.isfinite(mark):
                contract_pnl += old_position * (mark - previous) * pv
            for f in contract_fills:
                contract_pnl += f["quantity"] * (mark - f["price"]) * pv
            pnl += contract_pnl
        fees = float(sum(f["commission"] for f in fills))
        return pnl, fees, stale

    def _update_previous_closes(self, date, previous_marks, contracts):
        for contract in contracts:
            bar = self._get_bar((date, contract))
            if bar is None:
                continue
            mark = self._mark_price(bar)
            if np.isfinite(mark):
                previous_marks[contract] = mark

    def _order_reason_v3(self, date, contract, instrument, positions, desired, forced):
        held = [c for c in positions if self._instrument_for_contract(c) == instrument]
        mapped = self.mapping.get((date, instrument))
        if held and mapped and any(c != mapped for c in held):
            return "roll"
        if contract in forced:
            return forced[contract]
        if desired.get(contract, 0) == 0 and int(self.directions.get((date, instrument), 0)) == 0:
            return "signal_exit"
        return "normal_rebalance"

    def _apply_buffer(self, optimal, positions, fraction):
        desired = {}
        current_by_instrument = {self._instrument_for_contract(c): c for c in positions}
        for contract, target in optimal.items():
            instrument = self._instrument_for_contract(contract)
            if current_by_instrument.get(instrument) not in {None, contract}:
                desired[contract] = target
                continue
            current = positions.get(contract, 0)
            desired[contract] = buffered_position(current, target, fraction)
        return {k: v for k, v in desired.items() if v != 0}

    # ---- scheduling (BacktestEngineV3._scheduled_targets) ------------------
    def _scheduled_targets(self, date, optimal, positions, equity, sizing_diag,
                           weekly_dates, rebalance_mode):
        is_weekly = date in weekly_dates
        normal_day = rebalance_mode == "daily" or is_weekly
        diag = {"normal_rebalance_days": int(normal_day), "emergency_vol_trigger_days": 0}
        forced = {}
        if normal_day:
            desired = self._apply_buffer(optimal, positions, BUFFER_FRACTION)
        else:
            desired = dict(positions)
            for contract in list(positions):
                instrument = self._instrument_for_contract(contract)
                direction = int(self.directions.get((date, instrument), 0))
                mapped = self.mapping.get((date, instrument))
                if direction == 0:
                    desired.pop(contract, None)
                    forced[contract] = "signal_exit"
                elif mapped and mapped != contract:
                    desired.pop(contract, None)
                    forced[contract] = "roll"
                    if mapped in optimal:
                        desired[mapped] = optimal[mapped]
                        forced[mapped] = "roll"
            trailing = float(sizing_diag.get("trailing_realized_volatility", np.nan))
            if rebalance_mode == "hybrid" and np.isfinite(trailing):
                trigger = trailing > ANNUAL_VOL_TARGET * EMERGENCY_VOL_RATIO
                diag["emergency_vol_trigger_days"] = int(trigger)
                if trigger:
                    for contract, current in list(desired.items()):
                        target = int(optimal.get(contract, 0))
                        if target == 0 or np.sign(target) != np.sign(current):
                            desired.pop(contract, None)
                            forced[contract] = "volatility_forced"
                        elif abs(target) < abs(current):
                            desired[contract] = target
                            forced[contract] = "volatility_forced"
        before_hard = dict(desired)
        self._scale_for_portfolio_constraints(date, desired, equity)
        for contract in set(before_hard) | set(desired):
            if before_hard.get(contract, 0) != desired.get(contract, 0):
                current = int(positions.get(contract, 0))
                after = int(desired.get(contract, 0))
                if current and (after == 0 or (np.sign(after) == np.sign(current)
                                               and abs(after) < abs(current))):
                    forced[contract] = "margin_forced"
        return desired, diag, forced


class SingleEngine(Engine):
    """BacktestEngineV42 for a single horizon (G1/G2)."""

    def calculate_targets(self, date, equity, scenario_target, portfolio_returns):
        active = {}
        for instrument, row in self.instrument_meta.iterrows():
            direction = int(self.directions.get((date, instrument), 0))
            if direction:
                active.setdefault(row["sector"], []).append((instrument, direction))
        targets = {}
        annualizer = math.sqrt(ANNUALIZATION)
        for sector, legs in active.items():
            per_leg = equity * scenario_target * SECTOR_WEIGHTS[sector] / len(legs)
            for instrument, direction in legs:
                contract = self.mapping.get((date, instrument))
                daily_vol = self.price_vol.get((date, instrument))
                if not contract or daily_vol is None or not np.isfinite(daily_vol) or daily_vol <= 0:
                    continue
                pv = self._contract_value(contract, "point_value", fallback(instrument)[0])
                one_lot = pv * daily_vol * annualizer
                lots = int(math.floor(per_leg / one_lot))
                liq = self.liquidity.get((date, instrument), {})
                if np.isfinite(liq.get("median_volume", np.nan)):
                    lots = min(lots, int(math.floor(float(liq["median_volume"]) * VOL_FRACTION)))
                if np.isfinite(liq.get("median_open_interest", np.nan)):
                    lots = min(lots, int(math.floor(float(liq["median_open_interest"]) * OI_FRACTION)))
                if lots > 0:
                    targets[contract] = direction * lots
        exante, div = self._scale_to_exante(date, targets, equity, scenario_target)
        trailing, realized = self._scale_by_realized(targets, portfolio_returns, scenario_target)
        self._scale_for_portfolio_constraints(date, targets, equity)
        return targets, {"exante_vol_before_scaling": exante, "diversification_multiplier": div,
                         "trailing_realized_volatility": trailing, "realized_vol_multiplier": realized}

    def run(self, dates, weekly_dates, scenario_name, fee_mult):
        equity = INITIAL_CAPITAL
        positions, lots, previous_marks, pending = {}, {}, {}, {}
        target_rows, portfolio_returns = [], []
        for date in dates:
            start_positions = positions.copy()
            day_fills = []
            for contract, order in list(pending.items()):
                order.attempts += 1
                fills, remainder, rejection = self._execute_order_v3(date, order, lots, fee_mult)
                for f in fills:
                    positions[contract] = positions.get(contract, 0) + int(f["quantity"])
                    if positions[contract] == 0:
                        positions.pop(contract, None)
                    day_fills.append(f)
            pending = {}
            gross_pnl, fees, _ = self._mark_to_market(date, start_positions, day_fills, previous_marks)
            equity_before = equity
            equity += gross_pnl - fees
            portfolio_returns.append((gross_pnl - fees) / equity_before)
            optimal, sizing = self.calculate_targets(date, equity, ANNUAL_VOL_TARGET, portfolio_returns)
            desired, schedule, forced = self._scheduled_targets(
                date, optimal, positions, equity, sizing, weekly_dates, "hybrid")
            for contract in sorted(set(positions) | set(desired)):
                quantity = int(desired.get(contract, 0) - positions.get(contract, 0))
                if quantity == 0:
                    continue
                instrument = self._instrument_for_contract(contract)
                reason = self._order_reason_v3(date, contract, instrument, positions, desired, forced)
                pending[contract] = PendingOrder(contract, instrument, quantity, date, reason)
            for contract, quantity in desired.items():
                target_rows.append({
                    "date": date, "contract": contract,
                    "instrument": self._instrument_for_contract(contract),
                    "optimal_position": int(optimal.get(contract, 0)),
                    "buffered_target": int(quantity),
                    "scenario": scenario_name,
                    "normal_rebalance_day": bool(schedule["normal_rebalance_days"]),
                    "emergency_trigger": bool(schedule["emergency_vol_trigger_days"])})
            self._update_previous_closes(date, previous_marks, set(positions) | set(start_positions))
        return pd.DataFrame(target_rows)


class SleeveEngine(Engine):
    """SleeveEngineV42 for S1 = single_20_skip5 + single_250."""

    def calculate_targets(self, date, equity, scenario_target, portfolio_returns):
        annualizer = math.sqrt(ANNUALIZATION)
        rows = []
        for horizon in sorted(self.directions_by_horizon):
            directions = self.directions_by_horizon[horizon]
            for sector, weight in SECTOR_WEIGHTS.items():
                legs = [(instrument, int(directions.get((date, instrument), 0)))
                        for instrument, row in self.instrument_meta.iterrows()
                        if row["sector"] == sector and directions.get((date, instrument), 0)]
                budget = equity * scenario_target * weight * 0.5
                if not legs:
                    rows.append({"date": date, "horizon": horizon, "sector": sector,
                                 "instrument": None, "contract": None, "direction": 0,
                                 "internal_target": 0, "allocated_annual_risk": budget,
                                 "internal_annual_risk": 0.0, "unused_annual_risk": budget,
                                 "risk_fraction": weight * 0.5, "equity": equity})
                    continue
                for instrument, direction in legs:
                    contract = self.mapping.get((date, instrument))
                    vol = self.price_vol.get((date, instrument), np.nan)
                    one_lot = 0.0
                    if contract and vol is not None and np.isfinite(vol) and vol > 0:
                        one_lot = self._contract_value(contract, "point_value",
                                                       fallback(instrument)[0]) * vol * annualizer
                    per_leg = budget / len(legs)
                    lots = int(math.floor(per_leg / one_lot)) if one_lot > 0 else 0
                    rows.append({"date": date, "horizon": horizon, "sector": sector,
                                 "instrument": instrument, "contract": contract,
                                 "direction": direction, "internal_target": direction * lots,
                                 "allocated_annual_risk": per_leg,
                                 "internal_annual_risk": lots * one_lot,
                                 "unused_annual_risk": per_leg - lots * one_lot,
                                 "risk_fraction": weight * 0.5 / len(legs), "equity": equity})
        self.internal_target_rows.extend(rows)
        net, gross = {}, {}
        for row in rows:
            c = row["contract"]
            q = int(row["internal_target"])
            if c:
                net[c] = net.get(c, 0) + q
                gross[c] = gross.get(c, 0) + abs(q)
        targets = {c: q for c, q in net.items() if q}
        self._cap_final_liquidity(date, targets)
        exante, div = self._scale_to_exante(date, targets, equity, scenario_target)
        trailing, realized = self._scale_by_realized(targets, portfolio_returns, scenario_target)
        return targets, {"exante_vol_before_scaling": exante, "diversification_multiplier": div,
                         "trailing_realized_volatility": trailing, "realized_vol_multiplier": realized}

    def run(self, dates, weekly_dates, scenario_name, fee_mult):
        equity = INITIAL_CAPITAL
        positions, lots, previous_marks, pending = {}, {}, {}, {}
        target_rows, portfolio_returns = [], []
        for date in dates:
            start_positions = positions.copy()
            day_fills = []
            for contract, order in list(pending.items()):
                order.attempts += 1
                fills, remainder, rejection = self._execute_order_v3(date, order, lots, fee_mult)
                for f in fills:
                    positions[contract] = positions.get(contract, 0) + int(f["quantity"])
                    if positions[contract] == 0:
                        positions.pop(contract, None)
                    day_fills.append(f)
            pending = {}
            gross_pnl, fees, _ = self._mark_to_market(date, start_positions, day_fills, previous_marks)
            equity_before = equity
            equity += gross_pnl - fees
            portfolio_returns.append((gross_pnl - fees) / equity_before)
            optimal, sizing = self.calculate_targets(date, equity, ANNUAL_VOL_TARGET, portfolio_returns)
            # SleeveEngineV42._scheduled_targets: temporarily expose net-target sign
            # as self.directions for exit/roll decisions.
            saved = {}
            for instrument in self.instrument_meta.index:
                key = (date, instrument)
                saved[key] = self.directions.get(key)
                target = int(optimal.get(self.mapping.get(key), 0))
                self.directions[key] = int(np.sign(target))
            try:
                desired, schedule, forced = self._scheduled_targets(
                    date, optimal, positions, equity, sizing, weekly_dates, "hybrid")
            finally:
                for key, value in saved.items():
                    if value is None:
                        self.directions.pop(key, None)
                    else:
                        self.directions[key] = value
            for contract in sorted(set(positions) | set(desired)):
                quantity = int(desired.get(contract, 0) - positions.get(contract, 0))
                if quantity == 0:
                    continue
                instrument = self._instrument_for_contract(contract)
                reason = self._order_reason_v3(date, contract, instrument, positions, desired, forced)
                pending[contract] = PendingOrder(contract, instrument, quantity, date, reason)
            for contract, quantity in desired.items():
                target_rows.append({
                    "date": date, "contract": contract,
                    "instrument": self._instrument_for_contract(contract),
                    "optimal_position": int(optimal.get(contract, 0)),
                    "buffered_target": int(quantity),
                    "scenario": scenario_name,
                    "normal_rebalance_day": bool(schedule["normal_rebalance_days"]),
                    "emergency_trigger": bool(schedule["emergency_vol_trigger_days"])})
            self._update_previous_closes(date, previous_marks, set(positions) | set(start_positions))
        return pd.DataFrame(target_rows)


# ----------------------------------------------------------------------------
# Comparison helpers
# ----------------------------------------------------------------------------
def compare_scores(mine, rec):
    m = mine.rename(columns={"score": "score_mine"})
    r = rec.rename(columns={"score": "score_rec"})
    j = m.merge(r, on=["date", "instrument"], how="outer", indicator=True)
    both = j[j["_merge"] == "both"].copy()
    diff = (both["score_mine"] - both["score_rec"]).abs()
    maxdiff = float(diff.max()) if len(diff) else 0.0
    exact = int((diff < 1e-12).sum())
    # sign agreement over rows where both are non-nan and non-zero recorded
    mask = both["score_mine"].notna() & both["score_rec"].notna() & (both["score_rec"] != 0)
    agree = int((np.sign(both.loc[mask, "score_mine"]) == np.sign(both.loc[mask, "score_rec"])).sum())
    n_comp = int(mask.sum())
    # NaN cells (lookback warmup / missing series) are also compared: both sides
    # must be NaN in the same cells.
    nan_mine = both["score_mine"].isna()
    nan_rec = both["score_rec"].isna()
    nan_agree = int((nan_mine & nan_rec).sum())
    return {"rows_recorded": len(r), "rows_mine": len(m), "rows_both": len(both),
            "rows_matched_exact": exact, "max_abs_diff": maxdiff,
            "sign_agreement_rate": (agree / n_comp) if n_comp else 1.0,
            "sign_comparable": n_comp,
            "nan_cells_matching": nan_agree,
            "nan_cells_total": int((nan_mine | nan_rec).sum())}


def compare_selections(mine, rec, key_cols):
    if "horizon" in rec.columns and "horizon" in mine.columns:
        key_cols = key_cols + ["horizon"]
    m = mine[key_cols + ["direction", "score"]].copy()
    r = rec[key_cols + ["direction", "score"]].copy()
    j = m.merge(r, on=key_cols, how="outer", suffixes=("_mine", "_rec"), indicator=True)
    both = j[j["_merge"] == "both"]
    dir_match = int((both["direction_mine"] == both["direction_rec"]).sum())
    score_diff = (both["score_mine"] - both["score_rec"]).abs()
    score_match = int((score_diff < 1e-12).sum())
    return {"rows_recorded": len(r), "rows_mine": len(m), "rows_both": len(both),
            "direction_matches": dir_match, "score_matches": score_match,
            "max_score_diff": float(score_diff.max()) if len(score_diff) else 0.0,
            "only_mine": int((j["_merge"] == "left_only").sum()),
            "only_recorded": int((j["_merge"] == "right_only").sum())}


def compare_targets(mine, rec):
    m = mine.rename(columns={"optimal_position": "opt_m", "buffered_target": "buf_m",
                             "normal_rebalance_day": "nrd_m", "emergency_trigger": "et_m"})
    r = rec.rename(columns={"optimal_position": "opt_r", "buffered_target": "buf_r",
                            "normal_rebalance_day": "nrd_r", "emergency_trigger": "et_r"})
    j = m.merge(r, on=["date", "contract"], how="outer", indicator=True)
    both = j[j["_merge"] == "both"]
    opt_match = int((both["opt_m"] == both["opt_r"]).sum())
    buf_match = int((both["buf_m"] == both["buf_r"]).sum())
    nrd_match = int((both["nrd_m"] == both["nrd_r"]).sum())
    et_match = int((both["et_m"] == both["et_r"]).sum())
    full_match = int(((both["opt_m"] == both["opt_r"]) & (both["buf_m"] == both["buf_r"])).sum())
    diffs = both[both["opt_m"].ne(both["opt_r"]) | both["buf_m"].ne(both["buf_r"])].copy()
    return {"rows_recorded": len(r), "rows_mine": len(m), "rows_both": len(both),
            "optimal_match": opt_match, "buffered_match": buf_match,
            "normal_rebalance_day_match": nrd_match, "emergency_trigger_match": et_match,
            "full_match": full_match, "only_mine": int((j["_merge"] == "left_only").sum()),
            "only_recorded": int((j["_merge"] == "right_only").sum()),
            "disagreements": diffs[["date", "contract", "opt_m", "opt_r", "buf_m", "buf_r"]].to_dict("records")}


def main():
    bars, mapping, adjusted, contract_meta, instrument_meta, calendar_daily, fee_rules = load()
    calendar = Calendar(calendar_daily)
    fee = FeeSchedule(fee_rules)

    prices = adjusted.pivot(index="date", columns="instrument", values="adjusted_price").sort_index()
    changes = prices.diff()
    daily_vol = robust_price_volatility(changes)
    eligibility, median_volume, median_oi = build_liquidity(mapping, bars, prices.index)
    library = {"prices": prices, "eligibility": eligibility,
               "median_volume": median_volume, "median_oi": median_oi,
               "daily_vol": daily_vol}

    score20 = price_diff_sharpe(changes, 20, 5)
    score250 = price_diff_sharpe(changes, 250, 0)

    b20 = build_bundle(score20, "single_20_skip5", library, instrument_meta, calendar)
    b250 = build_bundle(score250, "single_250", library, instrument_meta, calendar)
    sleeve = combined_sleeve_signal({"single_20_skip5": b20, "single_250": b250})

    data = {"bars": bars, "mapping": mapping, "adjusted_prices": adjusted,
            "contract_meta": contract_meta, "instrument_meta": instrument_meta}

    # engine dates + weekly signal dates over full mapping range
    all_dates = sorted(mapping["date"].unique())
    weekly_dates = set(calendar.weekly_signal_dates(all_dates))
    run_dates = pd.DatetimeIndex(
        [d for d in all_dates if RUN_START <= d <= RUN_END])

    # directions_by_horizon for the sleeve
    dirs_by_h = {
        "single_20_skip5": b20["directions"].set_index(["date", "instrument"])["direction"].to_dict(),
        "single_250": b250["directions"].set_index(["date", "instrument"])["direction"].to_dict(),
    }

    report = {"S1": {}, "G1": {}, "G2": {}}

    # ---- S1 (sleeve) ----
    s1_rec = OUT / "S1__strategy_sleeve_20skip5_250_equal_risk"
    report["S1"]["scores"] = compare_scores(
        sleeve["scores"], pd.read_pickle(s1_rec / "scores.pkl"))
    report["S1"]["selections"] = compare_selections(
        sleeve["selections"], pd.read_pickle(s1_rec / "selections.pkl"),
        ["signal_date", "sector", "instrument", "role"])
    eng = SleeveEngine(data, sleeve, fee, dirs_by_h)
    targets_mine = eng.run(run_dates, weekly_dates,
                           "S1__strategy_sleeve_20skip5_250_equal_risk", FEE_MULTIPLIER)
    targets_rec = pd.read_pickle(s1_rec / "targets.pkl")
    report["S1"]["targets"] = compare_targets(targets_mine, targets_rec)
    targets_mine.to_pickle(ART / "r4_recomputed_S1_targets.pkl")
    eng.internal_target_rows and pd.DataFrame(eng.internal_target_rows).to_pickle(
        ART / "r4_recomputed_S1_internal_targets.pkl")

    # ---- G1 / G2 (single horizon) ----
    for label, bundle, dname in [("G1", b20, "G1__single_20_skip5"),
                                 ("G2", b250, "G2__single_250")]:
        rec = OUT / dname
        report[label]["scores"] = compare_scores(
            bundle["scores"], pd.read_pickle(rec / "scores.pkl"))
        report[label]["selections"] = compare_selections(
            bundle["selections"], pd.read_pickle(rec / "selections.pkl"),
            ["signal_date", "sector", "instrument", "role"])
        eng = SingleEngine(data, bundle, fee)
        tm = eng.run(run_dates, weekly_dates, dname, FEE_MULTIPLIER)
        tr = pd.read_pickle(rec / "targets.pkl")
        report[label]["targets"] = compare_targets(tm, tr)

    (ART / "r4_recompute_comparison.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return report


if __name__ == "__main__":
    main()
