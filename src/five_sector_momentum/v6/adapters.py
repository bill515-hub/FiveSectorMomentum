from __future__ import annotations

from pathlib import Path

import pandas as pd

from .canonical import sha256_file
from .schemas import ensure_schema


BASELINES = {
    "v3_formal": {
        "root": Path("outputs/v3_20260902_001129"),
        "scenario": "00_formal__formal_baseline",
    },
    "v4_2_G1": {"root": Path("outputs/v4_2_20260903_091241"), "scenario": "G1__single_20_skip5"},
    "v4_2_G2": {"root": Path("outputs/v4_2_20260903_091241"), "scenario": "G2__single_250"},
    "v4_2_S1": {"root": Path("outputs/v4_2_20260903_091241"), "scenario": "S1__strategy_sleeve_20skip5_250_equal_risk"},
    "v4_2_S2": {"root": Path("outputs/v4_2_20260903_091241"), "scenario": "S2__strategy_sleeve_20skip5_250_equal_risk_fixed_3tick"},
}

CORE_ARTIFACTS = ("orders", "fills", "positions", "daily_equity")
SUPPORT_ARTIFACTS = (
    "targets",
    "scores",
    "selections",
    "directions",
    "internal_targets",
    "net_target_stages",
    "cost_attribution",
    "daily_pnl",
)


def _count_rows(path: Path) -> int | None:
    try:
        if path.suffix == ".pkl":
            return len(pd.read_pickle(path))
        return sum(1 for _ in path.open("r", encoding="utf-8-sig")) - 1
    except Exception:
        return None


def build_expected_artifact_inventory(project_root: Path) -> pd.DataFrame:
    records: list[dict] = []
    for baseline, spec in BASELINES.items():
        root = project_root / spec["root"]
        scenario_root = root / spec["scenario"]
        for artifact in (*CORE_ARTIFACTS, *SUPPORT_ARTIFACTS):
            candidates = [scenario_root / f"{artifact}.pkl", root / f"{artifact}.pkl"]
            selected = next((p for p in candidates if p.exists()), candidates[0])
            exists = selected.exists()
            requirement = "CORE" if artifact in CORE_ARTIFACTS else "SUPPORTING"
            if exists:
                status = "AVAILABLE"
                note = "whitelisted historical artifact; read-only"
            elif requirement == "CORE":
                status = "BLOCKER_MISSING_CORE"
                note = "core order/position/equity evidence is required for compatibility gate"
            else:
                status = "NOT_APPLICABLE"
                note = "historical run never produced this optional table"
            records.append(
                {
                    "baseline": baseline,
                    "scenario": spec["scenario"],
                    "artifact": artifact,
                    "path": str(selected.resolve()),
                    "requirement": requirement,
                    "exists": exists,
                    "status": status,
                    "rows": _count_rows(selected) if exists else None,
                    "sha256": sha256_file(selected) if exists else None,
                    "note": note,
                }
            )
    return ensure_schema("expected_artifact_inventory", records)


def read_whitelisted_pickle(project_root: Path, baseline: str, artifact: str) -> pd.DataFrame:
    if baseline not in BASELINES:
        raise KeyError(f"Unknown baseline {baseline}")
    if artifact not in (*CORE_ARTIFACTS, *SUPPORT_ARTIFACTS):
        raise KeyError(f"Unknown artifact {artifact}")
    spec = BASELINES[baseline]
    root = project_root / spec["root"]
    candidates = [root / spec["scenario"] / f"{artifact}.pkl", root / f"{artifact}.pkl"]
    selected = next((path for path in candidates if path.exists()), None)
    if selected is None:
        raise FileNotFoundError(f"{baseline}/{artifact}")
    return pd.read_pickle(selected)
