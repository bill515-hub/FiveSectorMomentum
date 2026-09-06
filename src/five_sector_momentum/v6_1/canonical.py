from __future__ import annotations

import hashlib
import json
import math
import struct
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


def _value(item: Any) -> Any:
    if item is None or item is pd.NA:
        return {"t": "null"}
    if isinstance(item, (pd.Timestamp, datetime, date)):
        return {"t": "datetime", "v": pd.Timestamp(item).isoformat()}
    if isinstance(item, (np.bool_, bool)):
        return {"t": "bool", "v": bool(item)}
    if isinstance(item, (np.integer, int)) and not isinstance(item, bool):
        return {"t": "int", "v": str(int(item))}
    if isinstance(item, (np.floating, float)):
        number = float(item)
        if math.isnan(number):
            return {"t": "float", "v": "nan"}
        if math.isinf(number):
            return {"t": "float", "v": "inf" if number > 0 else "-inf"}
        return {"t": "float64_be", "v": struct.pack(">d", number).hex()}
    if isinstance(item, Mapping):
        return {str(k): _value(item[k]) for k in sorted(item, key=str)}
    if isinstance(item, (list, tuple)):
        return [_value(x) for x in item]
    try:
        if pd.isna(item):
            return {"t": "null"}
    except (TypeError, ValueError):
        pass
    return {"t": "str", "v": str(item)}


def content_hash(value: Any) -> str:
    payload = json.dumps(_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def table_hash(frame: pd.DataFrame, sort_by: Iterable[str] | None = None) -> str:
    work = frame.copy()
    if sort_by:
        work = work.sort_values(list(sort_by), kind="mergesort", na_position="first")
    columns = sorted(map(str, work.columns))
    work = work.reindex(columns=columns).reset_index(drop=True)
    return content_hash({"serialization": "canonical_json_rows_v1", "columns": columns, "rows": work.to_dict("records")})


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_pair(frame: pd.DataFrame, base: Path) -> dict[str, Any]:
    base.parent.mkdir(parents=True, exist_ok=True)
    csv_path, pickle_path = base.with_suffix(".csv"), base.with_suffix(".pkl")
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    frame.to_pickle(pickle_path)
    return {"csv": str(csv_path.resolve()), "pickle": str(pickle_path.resolve()), "rows": len(frame), "content_sha256": table_hash(frame)}

