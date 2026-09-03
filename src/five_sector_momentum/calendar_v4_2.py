"""Independent exchange calendar. No prices or observed-bar endpoints are inputs."""
from pathlib import Path
import pandas as pd


class TradingCalendarV42:
    def __init__(self, daily: pd.DataFrame):
        frame = daily.copy()
        frame['date'] = pd.to_datetime(frame.date)
        if frame.duplicated(['exchange', 'date']).any():
            raise ValueError('Duplicate exchange calendar day')
        wide = frame.pivot(index='date', columns='exchange', values='is_open').sort_index()
        if not wide.stack().isin([0, 1]).all():
            raise ValueError('Unknown calendar open flag')
        if wide.max(axis=1).ne(wide.min(axis=1)).any():
            raise ValueError('Exchange calendars disagree; do not silently union conflicting sessions')
        if len(pd.date_range(wide.index.min(), wide.index.max()).difference(wide.index)):
            raise ValueError('Missing calendar dates')
        self.daily = pd.DataFrame({'date': wide.index, 'is_open': wide.max(axis=1).astype(int).values,
                                   'supporting_exchanges': wide.apply(lambda row: ','.join(row.dropna().index), axis=1).values})
        self.open_flags = self.daily.set_index('date').is_open

    @classmethod
    def load(cls, path: Path):
        return cls(pd.read_pickle(path))

    def weekly_signal_dates(self, observed_dates):
        dates = pd.DatetimeIndex(observed_dates)
        if dates.has_duplicates or not dates.is_monotonic_increasing:
            raise ValueError('Observed dates must be unique and sorted')
        signals=[]
        for date in dates:
            friday = date.to_period('W-FRI').end_time.normalize()
            rest = pd.date_range(date, friday)
            if not rest.isin(self.open_flags.index).all():
                raise ValueError(f'Incomplete independent calendar week at {date.date()}')
            if self.open_flags.loc[date] != 1:
                raise ValueError(f'Price on non-session {date.date()}')
            if self.open_flags.reindex(rest[1:]).sum() == 0:
                signals.append(date)
        return pd.DatetimeIndex(signals)

    def audit_observed_dates(self, observed_dates):
        dates = pd.DatetimeIndex(observed_dates).sort_values().unique()
        expected = self.open_flags.loc[dates.min():dates.max()]
        expected = expected[expected.eq(1)].index
        return pd.DataFrame([
            {'check': 'price_on_closed_day', 'count': len(dates.difference(expected))},
            {'check': 'open_day_without_any_price', 'count': len(expected.difference(dates))},
        ])
