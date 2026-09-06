from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


EXCHANGE_SUFFIX = {
    "CFFEX": "CFX",
    "DCE": "DCE",
    "CZCE": "ZCE",
    "SHFE": "SHF",
    "INE": "INE",
    "GFEX": "GFE",
}


@dataclass(frozen=True)
class InstrumentSpec:
    instrument: str
    exchange: str
    sector: str
    mode: str

    @property
    def continuous_code(self) -> str:
        return f"{self.instrument}.{EXCHANGE_SUFFIX[self.exchange]}"


# Fallback contract economics. Tushare fut_basic remains the preferred source.
# point_value is CNY per quoted price point per lot.
FALLBACK_ECONOMICS: dict[str, tuple[float, float, float]] = {
    "RB": (10.0, 1.0, 0.13), "T": (10000.0, 0.005, 0.03), "AL": (5.0, 5.0, 0.13),
    "A": (10.0, 1.0, 0.13), "B": (10.0, 1.0, 0.13), "C": (10.0, 1.0, 0.12),
    "CS": (10.0, 1.0, 0.12), "FB": (10.0, 0.5, 0.15), "BB": (500.0, 0.05, 0.20),
    "JD": (10.0, 1.0, 0.15), "LH": (16.0, 5.0, 0.18), "M": (10.0, 1.0, 0.12),
    "P": (10.0, 2.0, 0.13), "RR": (10.0, 1.0, 0.12), "Y": (10.0, 2.0, 0.13),
    "AP": (10.0, 1.0, 0.15), "CF": (5.0, 5.0, 0.12), "CJ": (5.0, 5.0, 0.15),
    "CY": (5.0, 5.0, 0.15), "JR": (20.0, 1.0, 0.15), "LR": (20.0, 1.0, 0.15),
    "OI": (10.0, 1.0, 0.13), "PK": (5.0, 2.0, 0.15), "PM": (50.0, 1.0, 0.15),
    "RI": (20.0, 1.0, 0.15), "RM": (10.0, 1.0, 0.13), "RS": (10.0, 1.0, 0.18),
    "SR": (10.0, 1.0, 0.12), "WH": (20.0, 1.0, 0.15),
    "BZ": (10.0, 1.0, 0.15), "EB": (5.0, 1.0, 0.15), "EG": (10.0, 1.0, 0.15),
    "L": (5.0, 1.0, 0.13), "PG": (20.0, 1.0, 0.18), "PP": (5.0, 1.0, 0.13),
    "V": (5.0, 1.0, 0.13), "FG": (20.0, 1.0, 0.15), "MA": (10.0, 1.0, 0.15),
    "PF": (5.0, 2.0, 0.15), "PR": (15.0, 2.0, 0.15), "PX": (5.0, 2.0, 0.15),
    "SA": (20.0, 1.0, 0.15), "SH": (30.0, 1.0, 0.18), "TA": (5.0, 2.0, 0.13),
    "UR": (20.0, 1.0, 0.15), "BR": (5.0, 5.0, 0.18), "BU": (10.0, 1.0, 0.15),
    "FU": (10.0, 1.0, 0.15), "RU": (10.0, 5.0, 0.15), "SP": (10.0, 2.0, 0.13),
    "LU": (10.0, 1.0, 0.15), "NR": (10.0, 5.0, 0.15), "SC": (1000.0, 0.1, 0.18),
}


def instruments_from_config(config: dict[str, Any]) -> list[InstrumentSpec]:
    specs: list[InstrumentSpec] = []
    exchange_by_absolute = {"RB": "SHFE", "T": "CFFEX", "AL": "SHFE"}
    for sector, instruments in config["absolute"].items():
        for instrument in instruments:
            specs.append(InstrumentSpec(instrument, exchange_by_absolute[instrument], sector, "absolute"))
    for sector, exchange_groups in config["cross_sectional"].items():
        for exchange, instruments in exchange_groups.items():
            for instrument in instruments:
                specs.append(InstrumentSpec(instrument, exchange, sector, "cross_sectional"))
    duplicates = pd.Series([item.instrument for item in specs]).value_counts()
    duplicate_codes = duplicates[duplicates > 1].index.tolist()
    if duplicate_codes:
        raise ValueError(f"Instruments assigned more than once: {duplicate_codes}")
    return specs


def instrument_frame(specs: list[InstrumentSpec]) -> pd.DataFrame:
    rows = []
    for spec in specs:
        point_value, tick_size, fallback_margin = FALLBACK_ECONOMICS.get(
            spec.instrument, (1.0, 1.0, 0.18)
        )
        rows.append(
            {
                "instrument": spec.instrument,
                "exchange": spec.exchange,
                "sector": spec.sector,
                "mode": spec.mode,
                "continuous_code": spec.continuous_code,
                "fallback_point_value": point_value,
                "fallback_tick_size": tick_size,
                "fallback_margin_rate": fallback_margin,
            }
        )
    return pd.DataFrame(rows).sort_values(["sector", "exchange", "instrument"]).reset_index(drop=True)

