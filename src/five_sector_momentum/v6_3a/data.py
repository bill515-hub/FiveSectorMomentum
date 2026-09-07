from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from five_sector_momentum.data_pipeline import DataBundle, build_panama_prices, load_bundle
from five_sector_momentum.settings import Settings

from .canonical import table_hash, write_pair


ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "data/v6_3a"
SOURCE_CODE = "V6_3A_CAUSAL_HOLD_NO_BACKWARD_EXPIRY"


def repair_mapping_causally(
    mapping: pd.DataFrame,
    bars: pd.DataFrame,
    contract_meta: pd.DataFrame,
    minimum_days_to_expiry: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forbid expiry-month reversals without consulting future observations.

    A previously accepted contract is held only when its same-day close and
    volume are usable and it still has the configured expiry runway.  No future
    volume, OI, price or performance enters the decision.
    """
    result = mapping.copy()
    result["date"] = pd.to_datetime(result["date"])
    bars = bars.copy()
    bars["date"] = pd.to_datetime(bars["date"])
    expiry = contract_meta.copy()
    expiry["delist_date"] = pd.to_datetime(expiry["delist_date"])
    expiry_by_contract = expiry.drop_duplicates("ts_code").set_index("ts_code")["delist_date"].to_dict()
    bar_lookup = bars.set_index(["date", "ts_code"])
    events: list[dict[str, Any]] = []

    for instrument, indexes in result.sort_values("date").groupby("instrument", sort=True).groups.items():
        accepted_contract: str | None = None
        accepted_expiry = pd.NaT
        for index in indexes:
            date = pd.Timestamp(result.at[index, "date"])
            proposed = str(result.at[index, "contract"])
            proposed_expiry = expiry_by_contract.get(proposed, pd.NaT)
            if accepted_contract is None:
                accepted_contract, accepted_expiry = proposed, proposed_expiry
                continue
            backward = pd.notna(accepted_expiry) and pd.notna(proposed_expiry) and proposed_expiry < accepted_expiry
            if not backward:
                accepted_contract, accepted_expiry = proposed, proposed_expiry
                continue

            key = (date, accepted_contract)
            if key not in bar_lookup.index:
                raise RuntimeError(f"V6_3A_HOLD_CONTRACT_MISSING_BAR:{instrument}:{date.date()}:{accepted_contract}")
            bar = bar_lookup.loc[key]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            volume = float(bar.get("volume", np.nan))
            close = float(bar.get("close", np.nan))
            days_left = int((accepted_expiry - date).days) if pd.notna(accepted_expiry) else -1
            if not np.isfinite(close) or close <= 0 or not np.isfinite(volume) or volume <= 0:
                raise RuntimeError(f"V6_3A_HELD_CONTRACT_NOT_EXECUTABLE:{instrument}:{date.date()}:{accepted_contract}")
            if days_left < int(minimum_days_to_expiry):
                raise RuntimeError(f"V6_3A_HELD_CONTRACT_EXPIRY_RUNWAY_FAILED:{instrument}:{date.date()}:{accepted_contract}")
            result.at[index, "contract"] = accepted_contract
            result.at[index, "source"] = SOURCE_CODE
            events.append({
                "date": date,
                "instrument": instrument,
                "proposed_contract": proposed,
                "accepted_contract": accepted_contract,
                "proposed_expiry": proposed_expiry,
                "accepted_expiry": accepted_expiry,
                "accepted_days_to_expiry": days_left,
                "accepted_volume": volume,
                "accepted_close": close,
                "reason_code": SOURCE_CODE,
                "used_future_data": False,
            })

    result = result.sort_values(["instrument", "date"], kind="mergesort").reset_index(drop=True)
    events_frame = pd.DataFrame(events)
    return result, events_frame


def expiry_transition_audit(mapping: pd.DataFrame, contract_meta: pd.DataFrame) -> pd.DataFrame:
    expiry = contract_meta.copy()
    expiry["delist_date"] = pd.to_datetime(expiry["delist_date"])
    lookup = expiry.drop_duplicates("ts_code").set_index("ts_code")["delist_date"]
    ordered = mapping.sort_values(["instrument", "date"], kind="mergesort").copy()
    ordered["expiry"] = ordered["contract"].map(lookup)
    ordered["previous_contract"] = ordered.groupby("instrument")["contract"].shift()
    ordered["previous_expiry"] = ordered.groupby("instrument")["expiry"].shift()
    changed = ordered["contract"].ne(ordered["previous_contract"])
    return ordered.loc[
        changed & ordered["expiry"].notna() & ordered["previous_expiry"].notna()
        & ordered["expiry"].lt(ordered["previous_expiry"])
    ].copy()


def build_corrected_bundle(settings: Settings, persist: bool = True) -> tuple[DataBundle, dict[str, Any]]:
    legacy = load_bundle(settings)
    corrected, events = repair_mapping_causally(
        legacy.mapping, legacy.bars, legacy.contract_meta,
        int(settings.section("roll")["minimum_days_to_expiry"]),
    )
    backwards = expiry_transition_audit(corrected, legacy.contract_meta)
    if not backwards.empty:
        raise AssertionError("V6_3A_BACKWARD_EXPIRY_REMAINS")
    multiple, adjusted, panama = build_panama_prices(settings, legacy.bars, corrected)
    if panama.get("stitch_failures"):
        raise AssertionError(f"V6_3A_PANAMA_STITCH_FAILURES:{panama['stitch_failures']}")
    bundle = replace(
        legacy,
        mapping=corrected,
        multiple_prices=multiple,
        adjusted_prices=adjusted,
        diagnostics={**legacy.diagnostics, "v6_3a": {
            "mapping_rule": SOURCE_CODE,
            "changed_rows": len(events),
            "panama": panama,
        }},
    )
    diagnostics = {
        "mapping_events": events,
        "backward_transitions": backwards,
        "changed_rows": int(len(events)),
        "changed_instruments": sorted(events.instrument.unique().tolist()) if not events.empty else [],
        "mapping_content_sha256": table_hash(corrected),
        "adjusted_content_sha256": table_hash(adjusted),
        "multiple_content_sha256": table_hash(multiple),
        "panama": panama,
    }
    if persist:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        write_pair(corrected, DATA_ROOT / "mapping_corrected")
        write_pair(multiple, DATA_ROOT / "multiple_prices_corrected")
        write_pair(adjusted, DATA_ROOT / "adjusted_prices_corrected")
        write_pair(events, DATA_ROOT / "mapping_correction_events")
        write_pair(backwards, DATA_ROOT / "mapping_backward_expiry_after_correction")
    return bundle, diagnostics


def load_corrected_bundle(settings: Settings) -> DataBundle:
    legacy = load_bundle(settings)
    mapping = pd.read_pickle(DATA_ROOT / "mapping_corrected.pkl")
    multiple = pd.read_pickle(DATA_ROOT / "multiple_prices_corrected.pkl")
    adjusted = pd.read_pickle(DATA_ROOT / "adjusted_prices_corrected.pkl")
    return replace(
        legacy,
        mapping=mapping,
        multiple_prices=multiple,
        adjusted_prices=adjusted,
        diagnostics={**legacy.diagnostics, "v6_3a_loaded": True},
    )


def prefix_invariance_check(settings: Settings, cutoff: str = "2020-12-31") -> pd.DataFrame:
    full, _ = build_corrected_bundle(settings, persist=False)
    legacy = load_bundle(settings)
    cutoff_date = pd.Timestamp(cutoff)
    prefix_mapping, _ = repair_mapping_causally(
        legacy.mapping.loc[pd.to_datetime(legacy.mapping.date).le(cutoff_date)].copy(),
        legacy.bars.loc[pd.to_datetime(legacy.bars.date).le(cutoff_date)].copy(),
        legacy.contract_meta,
        int(settings.section("roll")["minimum_days_to_expiry"]),
    )
    _, prefix_adjusted, diag = build_panama_prices(
        settings,
        legacy.bars.loc[pd.to_datetime(legacy.bars.date).le(cutoff_date)].copy(),
        prefix_mapping,
    )
    a = full.adjusted_prices.pivot(index="date", columns="instrument", values="adjusted_price").sort_index().diff()
    b = prefix_adjusted.pivot(index="date", columns="instrument", values="adjusted_price").sort_index().diff()
    dates = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    delta = (a.loc[dates, cols] - b.loc[dates, cols]).abs().stack().dropna()
    maximum = float(delta.max()) if not delta.empty else 0.0
    return pd.DataFrame([{
        "check": "corrected_mapping_and_panama_prefix_invariant",
        "cutoff": cutoff,
        "max_absolute_price_difference_delta": maximum,
        "prefix_stitch_failures": len(diag.get("stitch_failures", [])),
        "passed": maximum <= 1e-9 and not diag.get("stitch_failures"),
    }])

