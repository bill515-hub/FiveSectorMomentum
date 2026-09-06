"""Fixed-calendar selection with unchanged score, sign, ranking and sizing inputs."""
from typing import Any
import numpy as np
import pandas as pd
from .calendar_v4_2 import TradingCalendarV42
from .signals import SignalBundle, _wide_to_long, _selection_row

def weekly_select_v42(
    scores: pd.DataFrame, eligibility: pd.DataFrame,
    instrument_meta: pd.DataFrame, config: dict[str, Any], calendar: TradingCalendarV42
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if scores.empty:
        return pd.DataFrame(), pd.DataFrame(), {"weekly_signal_dates": 0}
    signal_dates = calendar.weekly_signal_dates(scores.index)
    meta = instrument_meta.set_index("instrument")
    instruments = list(meta.index)
    current = pd.Series(0, index=instruments, dtype=int)
    current_signal_date = pd.NaT
    direction_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    signal_date_set = set(pd.DatetimeIndex(signal_dates.values))

    for date in scores.index:
        if date in signal_date_set:
            current[:] = 0
            current_signal_date = date
            date_scores = scores.loc[date].where(eligibility.loc[date].reindex(scores.columns).fillna(False))
            for sector, sector_meta in meta.groupby("sector"):
                members = list(sector_meta.index)
                eligible = date_scores.reindex(members).dropna()
                mode = sector_meta["mode"].iloc[0]
                if mode == "cross_sectional":
                    if len(eligible) < int(config["min_eligible_instruments"]):
                        insufficient.append({"date": str(date.date()), "sector": sector, "eligible": len(eligible)})
                        continue
                    strongest = eligible.idxmax()
                    weakest = eligible.idxmin()
                    if eligible[strongest] > float(config["long_threshold"]):
                        current[strongest] = 1
                        selection_rows.append(_selection_row(date, sector, strongest, 1, eligible[strongest], "strongest"))
                    if weakest != strongest and eligible[weakest] < float(config["short_threshold"]):
                        current[weakest] = -1
                        selection_rows.append(_selection_row(date, sector, weakest, -1, eligible[weakest], "weakest"))
                else:
                    for instrument, score in eligible.items():
                        direction = int(score > float(config["long_threshold"])) - int(score < float(config["short_threshold"]))
                        current[instrument] = direction
                        if direction:
                            selection_rows.append(_selection_row(date, sector, instrument, direction, score, "absolute"))
        for instrument, direction in current.items():
            direction_rows.append(
                {"date": date, "signal_date": current_signal_date, "instrument": instrument,
                 "sector": meta.loc[instrument, "sector"], "direction": int(direction)}
            )
    selections = pd.DataFrame(selection_rows)
    directions = pd.DataFrame(direction_rows)
    diagnostics = {
        "weekly_signal_dates": len(signal_date_set),
        "first_signal_date": str(min(signal_date_set).date()) if signal_date_set else None,
        "last_signal_date": str(max(signal_date_set).date()) if signal_date_set else None,
        "insufficient_cross_sectional": insufficient,
    }
    return selections, directions, diagnostics



def signal_bundle_v42(settings, data, library, forecast, label, calendar):
    scores = forecast.reindex(index=library.prices.index, columns=library.prices.columns)
    selections, directions, diagnostics = weekly_select_v42(scores, library.eligibility, data.instrument_meta, settings.section('signal'), calendar)
    liquidity = _wide_to_long(library.median_volume, 'median_volume').merge(_wide_to_long(library.median_open_interest, 'median_open_interest'), on=['date','instrument'], how='outer')
    diagnostics.update({'forecast_label': label, 'calendar': 'independent_exchange_calendar', 'scheduled_dates': [str(x.date()) for x in calendar.weekly_signal_dates(scores.index)]})
    return SignalBundle(_wide_to_long(scores, 'score'), _wide_to_long(library.daily_vol, 'daily_price_vol'), _wide_to_long(library.eligibility, 'eligible'), liquidity, selections, directions, diagnostics)
