from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import tushare as ts

from .settings import Settings
from .storage import write_frame, write_json
from .universe import InstrumentSpec, instrument_frame, instruments_from_config


def load_local_env(project_root: Path) -> None:
    """Load simple KEY=VALUE pairs without ever logging their values."""
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class DownloadResult:
    basics: pd.DataFrame
    mappings: pd.DataFrame
    bars: pd.DataFrame
    settlements: pd.DataFrame
    limits: pd.DataFrame
    manifest: dict[str, Any]


class TushareFuturesSource:
    def __init__(self, settings: Settings, pause_seconds: float = 0.15):
        self.settings = settings
        project_root = settings.path.parent.parent
        load_local_env(project_root)
        token_name = settings.section("data")["token_env"]
        token = os.getenv(token_name)
        if not token:
            raise RuntimeError(
                f"Missing {token_name}. Put it in the process environment or local .env file."
            )
        self._token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[-8:]
        self.pro = ts.pro_api(token)
        self.pause_seconds = pause_seconds
        self.api_calls: dict[str, int] = {}
        self.warnings: list[str] = []

    def _call(self, name: str, retries: int = 4, **kwargs: Any) -> pd.DataFrame:
        method: Callable[..., pd.DataFrame] = getattr(self.pro, name)
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                frame = method(**kwargs)
                self.api_calls[name] = self.api_calls.get(name, 0) + 1
                time.sleep(self.pause_seconds)
                return frame if frame is not None else pd.DataFrame()
            except Exception as exc:  # SDK raises several non-public exception types
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(min(8.0, 0.5 * (2**attempt)))
        raise RuntimeError(f"Tushare {name} failed after {retries} attempts: {last_error}") from last_error

    def download(self, include_settlements: bool = True, include_limits: bool = True) -> DownloadResult:
        specs = instruments_from_config(self.settings.section("universe"))
        start = pd.Timestamp(self.settings.section("run")["warmup_start"])
        end = pd.Timestamp(self.settings.section("run")["end"])

        basics = self._download_basics()
        mappings = self._download_mappings(specs, start, end)
        contract_windows = self._contract_windows(specs, basics, mappings, start, end)
        bars = self._download_contract_endpoint("fut_daily", contract_windows)
        # fut_settle / ft_limit do not accept comma-separated multi-contract codes:
        # they silently return an empty frame for a batched call (see T2a root cause).
        # Fetch one contract per call so the endpoint returns real rows.
        settlements = (
            self._download_contract_endpoint("fut_settle", contract_windows, optional=True, batch_size=1)
            if include_settlements else pd.DataFrame()
        )
        limits = (
            self._download_contract_endpoint("ft_limit", contract_windows, optional=True, batch_size=1)
            if include_limits else pd.DataFrame()
        )

        output = self.settings.data_root / "raw" / "tushare"
        paths = {
            "instrument_universe": write_frame(instrument_frame(specs), output / "instrument_universe"),
            "fut_basic": write_frame(basics, output / "fut_basic"),
            "fut_mapping": write_frame(mappings, output / "fut_mapping"),
            "fut_daily": write_frame(bars, output / "fut_daily"),
            "fut_settle": write_frame(settlements, output / "fut_settle"),
            "ft_limit": write_frame(limits, output / "ft_limit"),
        }
        manifest = {
            "source": "tushare",
            "downloaded_at_utc": pd.Timestamp.utcnow().isoformat(),
            "range": [str(start.date()), str(end.date())],
            "token_fingerprint": f"sha256:...{self._token_fingerprint}",
            "api_calls": self.api_calls,
            "warnings": self.warnings,
            "rows": {
                "basics": len(basics), "mappings": len(mappings), "bars": len(bars),
                "settlements": len(settlements), "limits": len(limits),
            },
            "files": {key: str(value) for key, value in paths.items()},
        }
        write_json(manifest, output / "manifest.json")
        return DownloadResult(basics, mappings, bars, settlements, limits, manifest)

    def repair_missing_bars(self) -> dict[str, Any]:
        """Repair contracts present in vendor mapping but omitted by a batch response."""
        from .storage import read_frame, read_json

        raw_root = self.settings.data_root / "raw" / "tushare"
        basics = read_frame(raw_root / "fut_basic")
        mappings = read_frame(raw_root / "fut_mapping")
        bars = read_frame(raw_root / "fut_daily")
        specs = instruments_from_config(self.settings.section("universe"))
        start = pd.Timestamp(self.settings.section("run")["warmup_start"])
        end = pd.Timestamp(self.settings.section("run")["end"])
        windows = self._contract_windows(specs, basics, mappings, start, end)
        missing = windows[~windows["contract"].isin(set(bars["ts_code"]))]
        repaired = self._download_contract_endpoint("fut_daily", missing, batch_size=1)
        combined = (
            pd.concat([bars, repaired], ignore_index=True)
            .drop_duplicates(["ts_code", "trade_date"], keep="last")
        )
        path = write_frame(combined, raw_root / "fut_daily")
        manifest_path = raw_root / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["rows"]["bars"] = len(combined)
        previous_calls = manifest.get("api_calls", {})
        manifest["api_calls"] = {
            key: previous_calls.get(key, 0) + self.api_calls.get(key, 0)
            for key in set(previous_calls) | set(self.api_calls)
        }
        manifest.setdefault("repairs", []).append(
            {"repaired_at_utc": pd.Timestamp.utcnow().isoformat(),
             "requested_contracts": len(missing), "returned_contracts": repaired["ts_code"].nunique() if not repaired.empty else 0,
             "rows_added": len(combined) - len(bars), "file": str(path)}
        )
        write_json(manifest, manifest_path)
        return manifest["repairs"][-1]

    def _download_basics(self) -> pd.DataFrame:
        frames = []
        fields = (
            "ts_code,symbol,exchange,name,fut_code,multiplier,trade_unit,per_unit,"
            "quote_unit,quote_unit_desc,list_date,delist_date,d_month,last_ddate,trade_time_desc"
        )
        for exchange in self.settings.section("data")["exchanges"]:
            try:
                frame = self._call("fut_basic", exchange=exchange, fut_type="1", fields=fields)
            except RuntimeError as exc:
                self.warnings.append(f"fut_basic {exchange}: {exc}")
                continue
            frames.append(frame)
        nonempty = [frame for frame in frames if not frame.empty]
        return pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()

    def _download_mappings(
        self, specs: list[InstrumentSpec], start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        frames = []
        for spec in specs:
            try:
                frame = self._call(
                    "fut_mapping", ts_code=spec.continuous_code,
                    start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                )
            except RuntimeError as exc:
                self.warnings.append(f"fut_mapping {spec.continuous_code}: {exc}")
                continue
            if frame.empty:
                self.warnings.append(f"No vendor mapping for {spec.continuous_code}; OI fallback required")
                continue
            frame = frame.copy()
            frame["instrument"] = spec.instrument
            frame["exchange_name"] = spec.exchange
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _contract_windows(
        self, specs: list[InstrumentSpec], basics: pd.DataFrame, mappings: pd.DataFrame,
        start: pd.Timestamp, end: pd.Timestamp,
    ) -> pd.DataFrame:
        windows: list[dict[str, Any]] = []
        mapped_instruments: set[str] = set()
        basic_lookup = pd.DataFrame()
        if not basics.empty:
            basic_lookup = basics.copy()
            basic_lookup["list_date"] = pd.to_datetime(basic_lookup["list_date"], errors="coerce")
            basic_lookup["delist_date"] = pd.to_datetime(basic_lookup["delist_date"], errors="coerce")
            basic_lookup = basic_lookup.drop_duplicates("ts_code", keep="last").set_index("ts_code")
        if not mappings.empty:
            temp = mappings.copy()
            temp["trade_date"] = pd.to_datetime(temp["trade_date"])
            for (instrument, contract), group in temp.groupby(["instrument", "mapping_ts_code"]):
                mapped_instruments.add(instrument)
                listed = basic_lookup.loc[contract, "list_date"] if contract in basic_lookup.index else pd.NaT
                delisted = basic_lookup.loc[contract, "delist_date"] if contract in basic_lookup.index else pd.NaT
                windows.append(
                    {
                        "instrument": instrument, "contract": contract,
                        "start": max(start, listed if pd.notna(listed) else group["trade_date"].min() - timedelta(days=15)),
                        "end": min(end, delisted if pd.notna(delisted) else group["trade_date"].max() + timedelta(days=15)),
                    }
                )
        # If vendor mapping is absent, download every listed contract for that product so OI can select it.
        if not basics.empty:
            basic = basics.copy()
            basic["fut_code"] = basic["fut_code"].astype(str).str.upper()
            basic["list_date"] = pd.to_datetime(basic["list_date"], errors="coerce")
            basic["delist_date"] = pd.to_datetime(basic["delist_date"], errors="coerce")
            for spec in specs:
                if spec.instrument in mapped_instruments:
                    continue
                subset = basic[(basic["fut_code"] == spec.instrument) & (basic["exchange"] == spec.exchange)]
                for row in subset.itertuples(index=False):
                    contract_start = max(start, row.list_date) if pd.notna(row.list_date) else start
                    contract_end = min(end, row.delist_date) if pd.notna(row.delist_date) else end
                    if contract_start <= contract_end:
                        windows.append(
                            {"instrument": spec.instrument, "contract": row.ts_code,
                             "start": contract_start, "end": contract_end}
                        )
        return pd.DataFrame(windows).drop_duplicates("contract") if windows else pd.DataFrame()

    def _download_contract_endpoint(
        self, endpoint: str, windows: pd.DataFrame, optional: bool = False,
        batch_size: int = 6,
    ) -> pd.DataFrame:
        frames = []
        if windows.empty:
            return pd.DataFrame()
        # Tushare accepts comma-separated contract codes. Six ordinary contracts
        # stay comfortably below the 2,000-row endpoint limit in normal cases.
        windows = windows.sort_values(["instrument", "start", "contract"]).reset_index(drop=True)
        instrument_by_contract = windows.set_index("contract")["instrument"].to_dict()
        for offset in range(0, len(windows), batch_size):
            batch = windows.iloc[offset : offset + batch_size]
            contracts = ",".join(batch["contract"].astype(str))
            try:
                frame = self._call(
                    endpoint, ts_code=contracts,
                    start_date=pd.Timestamp(batch["start"].min()).strftime("%Y%m%d"),
                    end_date=pd.Timestamp(batch["end"].max()).strftime("%Y%m%d"),
                )
            except RuntimeError as exc:
                if optional:
                    self.warnings.append(
                        f"{endpoint} unavailable; endpoint disabled after first failed batch: {exc}"
                    )
                    break
                raise
            if not frame.empty:
                frame = frame.copy()
                frame["instrument"] = frame["ts_code"].map(instrument_by_contract)
                frame = frame[frame["instrument"].notna()]
                frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
