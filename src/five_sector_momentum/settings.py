from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    """Thin validated wrapper around the YAML configuration."""

    raw: dict[str, Any]
    path: Path

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        config_path = Path(path).resolve()
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        if not isinstance(raw, dict):
            raise ValueError("Configuration root must be a mapping")
        cls._validate(raw)
        return cls(raw=raw, path=config_path)

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        required = {"run", "data", "signal", "volatility", "eligibility", "portfolio", "execution", "roll", "universe"}
        missing = required.difference(raw)
        if missing:
            raise ValueError(f"Missing configuration sections: {sorted(missing)}")
        weights = raw["portfolio"]["sector_risk_weights"]
        if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
            raise ValueError("Sector risk weights must sum to one")
        if raw["signal"]["price"] != "close":
            raise ValueError("This research specification requires close-price signals")
        if raw["signal"]["method"] != "price_diff_sharpe":
            raise ValueError("This research specification requires price-difference Sharpe")
        buffer_fraction = float(raw["portfolio"]["position_buffer_fraction"])
        if not 0 <= buffer_fraction < 1:
            raise ValueError("position_buffer_fraction must be in [0, 1)")
        split = raw["run"]["sample_split"]
        if not (raw["run"]["start"] < split <= raw["run"]["end"]):
            raise ValueError("sample_split must fall inside the backtest range")

    def section(self, name: str) -> dict[str, Any]:
        return self.raw[name]

    @property
    def data_root(self) -> Path:
        root = Path(self.raw["data"]["root"])
        if not root.is_absolute():
            root = self.path.parent.parent / root
        return root.resolve()
