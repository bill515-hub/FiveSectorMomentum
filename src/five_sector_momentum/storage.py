from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd


HAS_PARQUET = importlib.util.find_spec("pyarrow") is not None


def write_frame(frame: pd.DataFrame, path_without_suffix: str | Path) -> Path:
    base = Path(path_without_suffix)
    base.parent.mkdir(parents=True, exist_ok=True)
    if HAS_PARQUET:
        target = base.with_suffix(".parquet")
        frame.to_parquet(target, index=False)
    else:
        target = base.with_suffix(".pkl")
        frame.to_pickle(target)
    return target


def read_frame(path_without_suffix: str | Path) -> pd.DataFrame:
    base = Path(path_without_suffix)
    parquet = base.with_suffix(".parquet")
    pickle = base.with_suffix(".pkl")
    if parquet.exists():
        return pd.read_parquet(parquet)
    if pickle.exists():
        return pd.read_pickle(pickle)
    raise FileNotFoundError(f"No table found for {base}")


def write_json(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    return target


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)

