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


def _canon(value: Any) -> Any:
    if value is None or value is pd.NA:
        return {"type": "null"}
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return {"type": "datetime", "value": pd.Timestamp(value).isoformat()}
    if isinstance(value, (np.bool_, bool)):
        return {"type": "bool", "value": bool(value)}
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return {"type": "int", "value": str(int(value))}
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number):
            return {"type": "float", "value": "nan"}
        if math.isinf(number):
            return {"type": "float", "value": "inf" if number > 0 else "-inf"}
        return {"type": "float64_be", "value": struct.pack(">d", number).hex()}
    if isinstance(value, Path):
        return {"type": "string", "value": value.as_posix()}
    if isinstance(value, Mapping):
        return {str(k): _canon(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    try:
        if pd.isna(value):
            return {"type": "null"}
    except (TypeError, ValueError):
        pass
    return {"type": "string", "value": str(value)}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(_canon(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_dataframe_hash(frame: pd.DataFrame, sort_by: Iterable[str] | None = None) -> str:
    table = frame.copy()
    if sort_by:
        table = table.sort_values(list(sort_by), kind="mergesort", na_position="first")
    columns = sorted(str(c) for c in table.columns)
    table = table.reindex(columns=columns)
    rows = [{c: row[c] for c in columns} for _, row in table.reset_index(drop=True).iterrows()]
    return canonical_json_hash({"serialization": "canonical_json_rows_v1", "columns": columns, "rows": rows})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_table_pair(frame: pd.DataFrame, base_path: Path) -> dict[str, str]:
    base_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = base_path.with_suffix(".csv")
    pkl_path = base_path.with_suffix(".pkl")
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    frame.to_pickle(pkl_path)
    return {
        "csv": str(csv_path),
        "pickle": str(pkl_path),
        "content_sha256": canonical_dataframe_hash(frame),
        "csv_sha256": sha256_file(csv_path),
        "pickle_sha256": sha256_file(pkl_path),
    }

